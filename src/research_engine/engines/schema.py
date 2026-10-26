"""Restricted JSON Schema 2020-12 validator and attribute sanitizer for domain packs.

Enforces INV-035:
- Rejects any $ref (especially http://, https://, file://, or .. path traversal).
- Supports flat/shallow object schemas with scalar/enum/array properties.
- Validates extracted attributes field-by-field: invalid fields are dropped and
  recorded in validation_notes rather than discarding a verified quote/claim.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

log = logging.getLogger(__name__)

ALLOWED_SCHEMA_TYPES = frozenset({"string", "number", "integer", "boolean", "array"})
MAX_RECOMMENDED_PROPERTIES = 8


class DomainSchemaError(ValueError):
    """Raised when an engine pack's schema.json violates the restricted subset."""


def _scan_for_forbidden_refs(node: Any, path: str = "$") -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            cur = f"{path}.{k}"
            if k == "$ref":
                raise DomainSchemaError(
                    f"forbidden $ref at {cur} ({v!r}): external or internal $ref is not allowed in engine domain schemas"
                )
            _scan_for_forbidden_refs(v, cur)
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            _scan_for_forbidden_refs(item, f"{path}[{idx}]")


def validate_domain_schema_dict(schema: dict[str, Any]) -> list[str]:
    """Validate a domain schema dict against the restricted JSON Schema 2020-12 subset.

    Returns a list of non-fatal warnings (e.g., >8 properties).
    Raises DomainSchemaError on any structural or security violation.
    """
    if not isinstance(schema, dict):
        raise DomainSchemaError("domain schema must be a JSON object")
    _scan_for_forbidden_refs(schema)

    if schema.get("type", "object") != "object":
        raise DomainSchemaError("domain schema root 'type' must be 'object'")

    props = schema.get("properties", {})
    if not isinstance(props, dict):
        raise DomainSchemaError("domain schema 'properties' must be an object")

    warnings: list[str] = []
    if len(props) > MAX_RECOMMENDED_PROPERTIES:
        warnings.append(
            f"domain schema defines {len(props)} properties (> {MAX_RECOMMENDED_PROPERTIES} recommended for local LLMs)"
        )

    for prop_name, prop_spec in props.items():
        if not isinstance(prop_spec, dict):
            raise DomainSchemaError(f"property '{prop_name}' definition must be an object")
        ptype = prop_spec.get("type")
        if ptype not in ALLOWED_SCHEMA_TYPES:
            raise DomainSchemaError(
                f"property '{prop_name}' has unsupported type {ptype!r}; allowed: {sorted(ALLOWED_SCHEMA_TYPES)}"
            )
        if ptype == "array":
            items = prop_spec.get("items", {})
            if not isinstance(items, dict) or items.get("type") not in {"string", "number", "integer", "boolean"}:
                raise DomainSchemaError(
                    f"array property '{prop_name}' must specify scalar items.type"
                )
        if "enum" in prop_spec:
            enum_vals = prop_spec["enum"]
            if not isinstance(enum_vals, list) or not enum_vals:
                raise DomainSchemaError(f"property '{prop_name}' enum must be a non-empty list")

    req = schema.get("required", [])
    if not isinstance(req, list) or any(not isinstance(r, str) or r not in props for r in req):
        raise DomainSchemaError("domain schema 'required' must be a list of defined property names")

    return warnings


def load_domain_schema(pack_dir: Path, rel_path: str) -> tuple[dict[str, Any], list[str]]:
    """Safely load and validate a domain schema inside pack_dir."""
    if not rel_path or ".." in Path(rel_path).parts or rel_path.startswith(("/", "\\")):
        raise DomainSchemaError(f"invalid domain_schema path {rel_path!r}: must be relative to pack directory")
    target = (pack_dir / rel_path).resolve()
    root = pack_dir.resolve()
    if root not in target.parents and target != root:
        raise DomainSchemaError(f"domain_schema path {rel_path!r} escapes pack directory")
    if not target.is_file():
        raise DomainSchemaError(f"domain_schema file not found: {target}")
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DomainSchemaError(f"invalid JSON in domain_schema {rel_path}: {exc}") from exc
    warnings = validate_domain_schema_dict(data)
    return data, warnings


def _field_definition(prop_name: str, prop_spec: dict[str, Any], is_required: bool) -> tuple[Any, Any]:
    ptype = prop_spec.get("type", "string")
    kwargs: dict[str, Any] = {}
    if "minimum" in prop_spec:
        kwargs["ge"] = prop_spec["minimum"]
    if "maximum" in prop_spec:
        kwargs["le"] = prop_spec["maximum"]

    if ptype == "string":
        py_type: Any = str
    elif ptype == "number":
        py_type = float
    elif ptype == "integer":
        py_type = int
    elif ptype == "boolean":
        py_type = bool
    elif ptype == "array":
        item_t = prop_spec.get("items", {}).get("type", "string")
        elem_type = {"string": str, "number": float, "integer": int, "boolean": bool}.get(item_t, str)
        py_type = list[elem_type]  # type: ignore[valid-type]
    else:
        py_type = Any

    if is_required:
        return (py_type, Field(..., **kwargs))
    return (py_type | None, Field(default=None, **kwargs))


def build_attributes_model(schema: dict[str, Any]) -> type[BaseModel]:
    """Create a dynamic Pydantic model for full-object validation of domain attributes."""
    validate_domain_schema_dict(schema)
    props = schema.get("properties", {})
    req = set(schema.get("required", []))
    fields: dict[str, Any] = {}
    for name, spec in props.items():
        fields[name] = _field_definition(name, spec, name in req)
    extra_mode = "forbid" if schema.get("additionalProperties") is False else "allow"
    return create_model(
        "DomainAttributesModel",
        __config__=ConfigDict(extra=extra_mode),
        **fields,
    )


def validate_attributes_field_by_field(
    schema: dict[str, Any] | None,
    raw_attrs: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    """Validate raw_attrs against schema field-by-field.

    Invalid or unknown fields (when additionalProperties is False) are dropped
    and recorded in notes rather than rejecting the entire Evidence item.
    """
    if not raw_attrs or not isinstance(raw_attrs, dict):
        return {}, []
    if not schema:
        return dict(raw_attrs), []

    props = schema.get("properties", {})
    allow_extra = schema.get("additionalProperties", True) is not False
    cleaned: dict[str, Any] = {}
    notes: list[str] = []

    for k, v in raw_attrs.items():
        if v is None:
            continue
        if k not in props:
            if allow_extra:
                cleaned[k] = v
            else:
                notes.append(f"dropped unknown attribute '{k}'")
            continue
        spec = props[k]
        if "enum" in spec and v not in spec["enum"]:
            notes.append(f"dropped attribute '{k}': value {v!r} not in enum {spec['enum']}")
            continue
        single_model = create_model(
            f"Attr_{k}",
            val=_field_definition(k, spec, True),
        )
        try:
            validated = single_model.model_validate({"val": v})
            cleaned[k] = getattr(validated, "val")
        except ValidationError as exc:
            err_msg = exc.errors()[0].get("msg", "invalid value") if exc.errors() else "invalid value"
            notes.append(f"dropped attribute '{k}': {err_msg}")

    for req_field in schema.get("required", []):
        if req_field not in cleaned and raw_attrs:
            notes.append(f"missing required domain attribute '{req_field}'")

    return cleaned, notes


def format_domain_schema_hint(schema: dict[str, Any] | None) -> str:
    """Format a compact schema description for prompt injection."""
    if not schema or not schema.get("properties"):
        return "(none)"
    parts: list[str] = []
    req = set(schema.get("required", []))
    for name, spec in schema.get("properties", {}).items():
        ptype = spec.get("type", "string")
        if "enum" in spec:
            ptype = f"enum{spec['enum']}"
        elif ptype == "array":
            item_t = spec.get("items", {}).get("type", "string")
            ptype = f"list[{item_t}]"
        req_marker = " (required)" if name in req else ""
        parts.append(f"{name}: {ptype}{req_marker}")
    return "attributes: { " + "; ".join(parts) + " }"
