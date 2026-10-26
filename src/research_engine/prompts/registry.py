"""Versioned prompt template registry.

prompts/templates/<name>/<version>.txt with optional <version>.meta.yaml
(system prompt, role assignment). Prompts are externalized, never inlined.
Engine packs may override or add templates under <pack_dir>/prompts/<name>/.
Rendered copies are saved to the project workspace for audit.
"""
from __future__ import annotations

import functools
import logging
import re
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")
_VERSION_STEM_RE = re.compile(r"^v([0-9]+)$")

# Decision: a missing templates directory is an incomplete INSTALLATION, not a
# missing prompt. The two failures need different fixes, so they get different
# messages.
# Why: the templates are package data; if they are absent, the wheel was built
# without them and every prompt render will fail. An actionable message beats a
# bare FileNotFoundError from iterdir().
_INSTALL_INCOMPLETE = (
    "prompt templates directory is missing at {path}. The installation is "
    "incomplete (package data was not installed). Reinstall with "
    "`pip install .` or use an editable install (`pip install -e .`)."
)


def _require_templates_dir() -> None:
    if not TEMPLATES_DIR.is_dir():
        raise FileNotFoundError(_INSTALL_INCOMPLETE.format(path=TEMPLATES_DIR))


def _normalize_version(version: str | int) -> str:
    """Return canonical version string in 'vN' format (e.g. 'v1', 'v10')."""
    s = str(version).strip()
    if s.startswith("v"):
        digits = s[1:]
    else:
        digits = s
    if not digits.isdigit():
        raise ValueError(f"invalid prompt version {version!r}; expected 'v<digits>' or '<digits>'")
    return f"v{int(digits)}"


def _sorted_versions(base: Path) -> list[str]:
    """Return canonical 'vN' versions under ``base`` sorted numerically."""
    valid: list[tuple[int, str]] = []
    for p in base.glob("v*.txt"):
        m = _VERSION_STEM_RE.match(p.stem)
        if not m:
            log.warning("ignoring malformed prompt version filename %s in %s", p.name, base)
            continue
        num = int(m.group(1))
        valid.append((num, f"v{num}"))
    valid.sort(key=lambda item: item[0])
    return [v for _, v in valid]


class PromptSpec:
    def __init__(self, name: str, version: str, system: str, template: str):
        self.name = name
        self.version = _normalize_version(version)
        self.system = system
        self.template = template

    def render(self, **kwargs) -> str:
        # P1-8: Extract required placeholders from the RAW template BEFORE
        # substituting untrusted kwargs values. Braces inside scraped text or
        # user content must never be mistaken for unfilled template placeholders.
        for opt_k, opt_v in (("engine_guidance", ""), ("domain_schema_hint", "(none)")):
            kwargs.setdefault(opt_k, opt_v)
        required = [m.group(1) for m in _PLACEHOLDER_RE.finditer(self.template)]
        for key in required:
            if key not in kwargs:
                raise ValueError(f"unknown/unfilled placeholder '{key}' in prompt {self.name}")

        def _replace(match: re.Match[str]) -> str:
            key = match.group(1)
            return str(kwargs[key])

        return _PLACEHOLDER_RE.sub(_replace, self.template)


@functools.lru_cache(maxsize=None)
def _load(name: str, version: str | None = None, templates_dir: str = "") -> PromptSpec:
    root = Path(templates_dir) if templates_dir else TEMPLATES_DIR
    if not root.is_dir():
        raise FileNotFoundError(_INSTALL_INCOMPLETE.format(path=root))
    base = root / name
    if not base.exists():
        raise FileNotFoundError(f"prompt template '{name}' not found")
    if version is None:
        versions = _sorted_versions(base)
        if not versions:
            raise FileNotFoundError(f"no versions for prompt '{name}'")
        canon_ver = versions[-1]
    else:
        canon_ver = _normalize_version(version)
    txt_path = base / f"{canon_ver}.txt"
    if not txt_path.exists():
        raise FileNotFoundError(f"prompt template '{name}' version '{canon_ver}' not found")
    meta_path = base / f"{canon_ver}.meta.yaml"
    meta = {}
    if meta_path.exists():
        meta = yaml.safe_load(meta_path.read_text()) or {}
    return PromptSpec(name=name, version=canon_ver,
                      system=meta.get("system", ""),
                      template=txt_path.read_text())


def _resolve_engine_prompts_dir(engine: str | None, workspace_dir: str | Path | None = None) -> Path | None:
    if not engine:
        return None
    try:
        from research_engine.engines.loader import get_engine
        manifest = get_engine(engine, workspace_dir=workspace_dir)
        return manifest.prompts_dir()
    except Exception:
        return None


def get_prompt(
    name: str,
    version: str | None = None,
    engine: str | None = None,
    workspace_dir: str | Path | None = None,
) -> PromptSpec:
    _require_templates_dir()
    eng_pdir = _resolve_engine_prompts_dir(engine, workspace_dir=workspace_dir)
    if eng_pdir is not None and (eng_pdir / name).is_dir() and _sorted_versions(eng_pdir / name):
        return _load(name, version, str(eng_pdir))
    return _load(name, version, str(TEMPLATES_DIR))


def record_versions(
    engine: str | None = None,
    workspace_dir: str | Path | None = None,
) -> dict[str, str]:
    _require_templates_dir()
    out = {}
    for d in sorted(TEMPLATES_DIR.iterdir(), key=lambda p: p.name):
        if d.is_dir():
            versions = _sorted_versions(d)
            if versions:
                out[d.name] = versions[-1]
    eng_pdir = _resolve_engine_prompts_dir(engine, workspace_dir=workspace_dir)
    if eng_pdir is not None:
        for d in sorted(eng_pdir.iterdir(), key=lambda p: p.name):
            if d.is_dir():
                versions = _sorted_versions(d)
                if versions:
                    out[d.name] = f"{versions[-1]}@{engine}"
    return out
