"""Engine pack loader, inheritance resolver, static validator, and effective config builder."""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from research_engine.core.config import AppConfig, _coerce_env_value
from research_engine.core.state_machine import ALLOWED
from research_engine.engines.manifest import (
    EngineManifest,
    EngineValidationError,
    TunablesSpec,
)
from research_engine.engines.registry import (
    CORE_REPORT_FILES,
    DOMAIN_REPORT_REGISTRY,
    INTELLIGENCE_REPORT_REGISTRY,
    ITERATION_STEPS,
    METRIC_REGISTRY,
    PROMPT_CALLER_KWARGS,
    REASONING_REPORT_REGISTRY,
    SETUP_STEPS,
    SPECIALIST_REGISTRY,
    STEP_REGISTRY,
    STEP_TARGET_STATE,
    STOP_OPS,
    STRUCTURAL_CHECK_REGISTRY,
    SYNTHESIS_STEPS,
)
from research_engine.engines.schema import DomainSchemaError, load_domain_schema
from research_engine.engines.skills import load_pack_skills
from research_engine.models.enums import ProjectState

BUILTIN_DIR = Path(__file__).parent / "builtin"
_ENGINE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_CATEGORY_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")

_ENGINE_CACHE: dict[tuple[str, str], EngineManifest] = {}
_EXTRA_SEARCH_DIRS: list[Path] = []


def register_search_dir(path: str | Path) -> None:
    """Register an additional directory containing engine pack folders."""
    p = Path(path).resolve()
    if p not in _EXTRA_SEARCH_DIRS:
        _EXTRA_SEARCH_DIRS.insert(0, p)
    reload()


def clear_search_dirs() -> None:
    _EXTRA_SEARCH_DIRS.clear()
    reload()


def reload() -> None:
    """Clear cached engine manifests and prompt templates."""
    _ENGINE_CACHE.clear()
    try:
        from research_engine.prompts.registry import _load
        _load.cache_clear()
    except Exception:
        pass
    try:
        from research_engine.modes.base import _refresh_modes
        _refresh_modes()
    except Exception:
        pass


def _search_roots(workspace_dir: str | Path | None = None) -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    if workspace_dir:
        ws_p = Path(workspace_dir)
        if (ws_p / "engine" / "engine.yaml").is_file():
            roots.append(("project", ws_p))
        if (ws_p / "engines").is_dir():
            roots.append(("workspace", ws_p / "engines"))
    for extra in _EXTRA_SEARCH_DIRS:
        if extra.is_dir():
            roots.append(("custom", extra))
    env_dir = os.environ.get("GAR_ENGINES_DIR", "").strip()
    if env_dir and Path(env_dir).is_dir():
        roots.append(("env", Path(env_dir)))
    cwd_engines = Path.cwd() / "engines"
    if cwd_engines.is_dir():
        roots.append(("workspace", cwd_engines))
    user_cfg_engines = Path.home() / ".config" / "gar" / "engines"
    if user_cfg_engines.is_dir():
        roots.append(("user", user_cfg_engines))
    if BUILTIN_DIR.is_dir():
        roots.append(("builtin", BUILTIN_DIR))
    return roots


def discover_engine_dirs(workspace_dir: str | Path | None = None) -> dict[str, tuple[str, Path]]:
    """Return mapping of engine_name -> (source_layer, pack_dir), highest precedence winning."""
    found: dict[str, tuple[str, Path]] = {}
    for layer, root in _search_roots(workspace_dir):
        if layer == "project":
            pack = root / "engine"
            ey = pack / "engine.yaml"
            if ey.is_file():
                try:
                    raw = yaml.safe_load(ey.read_text(encoding="utf-8")) or {}
                    name = str(raw.get("name", "")).strip()
                    if name and name not in found:
                        found[name] = (layer, pack)
                except Exception:
                    pass
            continue
        for child in sorted(root.iterdir(), key=lambda p: p.name):
            if child.is_dir() and (child / "engine.yaml").is_file():
                name = child.name
                if name not in found:
                    found[name] = (layer, child)
    return found


def list_engines(workspace_dir: str | Path | None = None) -> list[EngineManifest]:
    discovered = discover_engine_dirs(workspace_dir)
    out: list[EngineManifest] = []
    for name in sorted(discovered):
        out.append(get_engine(name, workspace_dir=workspace_dir))
    return out


def engine_names(workspace_dir: str | Path | None = None) -> list[str]:
    return sorted(discover_engine_dirs(workspace_dir).keys())


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge two raw manifest dicts: dicts merge recursively, scalars and lists replace."""
    merged = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = copy.deepcopy(v)
    return merged


def _load_raw_with_Inheritance(
    name_or_dir: str | Path,
    discovered: dict[str, tuple[str, Path]],
    chain: list[str] | None = None,
) -> tuple[dict[str, Any], Path, str]:
    chain = list(chain or [])
    if isinstance(name_or_dir, Path) or (isinstance(name_or_dir, str) and ("/" in name_or_dir or "\\" in name_or_dir or Path(name_or_dir).is_dir())):
        p = Path(name_or_dir)
        pack_dir = p if p.is_dir() else p.parent
        ey = pack_dir / "engine.yaml"
        if not ey.is_file():
            raise EngineValidationError([f"engine.yaml not found at {ey}"])
        layer = "path"
    else:
        name = str(name_or_dir)
        if name not in discovered:
            raise ValueError(
                f"unknown mode/engine '{name}'; available: {sorted(discovered.keys())}"
            )
        layer, pack_dir = discovered[name]
        ey = pack_dir / "engine.yaml"

    try:
        raw = yaml.safe_load(ey.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise EngineValidationError([f"invalid YAML in {ey}: {exc}"]) from exc
    if not isinstance(raw, dict):
        raise EngineValidationError([f"{ey} must contain a YAML mapping"])

    eng_name = str(raw.get("name") or pack_dir.name)
    if eng_name in chain:
        cycle = " -> ".join([*chain, eng_name])
        raise EngineValidationError([f"inheritance cycle detected in 'extends': {cycle}"])
    if len(chain) >= 2:
        raise EngineValidationError([f"inheritance depth exceeds maximum of 2: {' -> '.join([*chain, eng_name])}"])

    parent_name = raw.get("extends")
    if parent_name:
        if str(parent_name) == eng_name:
            raise EngineValidationError([f"inheritance cycle detected: engine '{eng_name}' extends itself"])
        if str(parent_name) not in discovered:
            raise EngineValidationError([f"parent engine '{parent_name}' in 'extends' not found"])
        parent_raw, _, _ = _load_raw_with_Inheritance(
            str(parent_name), discovered, chain=[*chain, eng_name]
        )
        merged = _deep_merge(parent_raw, raw)
        merged["extends"] = parent_name
        return merged, pack_dir, layer

    return raw, pack_dir, layer


def _validate_tunables_bounds(t: TunablesSpec) -> list[str]:
    errs: list[str] = []
    if t.max_iterations is not None and not (1 <= t.max_iterations <= 20):
        errs.append(f"tunables.max_iterations={t.max_iterations} out of bounds [1, 20]")
    if t.max_queries_per_iteration is not None and not (1 <= t.max_queries_per_iteration <= 50):
        errs.append(
            f"tunables.max_queries_per_iteration={t.max_queries_per_iteration} out of bounds [1, 50]"
        )
    if t.new_evidence_threshold is not None and not (0.0 <= t.new_evidence_threshold <= 1.0):
        errs.append(
            f"tunables.new_evidence_threshold={t.new_evidence_threshold} out of bounds [0.0, 1.0]"
        )
    if t.duplicate_rate_converged is not None and not (0.0 <= t.duplicate_rate_converged <= 1.0):
        errs.append(
            f"tunables.duplicate_rate_converged={t.duplicate_rate_converged} out of bounds [0.0, 1.0]"
        )
    if (
        t.chunk_overlap_chars is not None
        and t.max_chunk_chars is not None
        and t.chunk_overlap_chars >= t.max_chunk_chars
    ):
        errs.append(
            f"tunables.chunk_overlap_chars ({t.chunk_overlap_chars}) must be < tunables.max_chunk_chars ({t.max_chunk_chars})"
        )
    if (
        t.max_documents is not None
        and t.max_sources_total is not None
        and t.max_documents > t.max_sources_total
    ):
        errs.append(
            f"tunables.max_documents ({t.max_documents}) must be <= tunables.max_sources_total ({t.max_sources_total})"
        )
    return errs


def _simulate_state_walk(manifest: EngineManifest) -> list[str]:
    """Walk setup -> per_iteration -> synthesis against ALLOWED state transitions."""
    errs: list[str] = []
    state = ProjectState.CREATED
    all_phases = [
        ("setup", manifest.loop.setup),
        ("per_iteration", manifest.loop.per_iteration),
        ("synthesis", manifest.loop.synthesis),
    ]
    for phase_name, steps in all_phases:
        if phase_name == "synthesis":
            # Before synthesis, loop converges to CONVERGED
            if ProjectState.CONVERGED not in ALLOWED.get(state, set()) and state != ProjectState.CONVERGED:
                errs.append(
                    f"loop state transition {state.value} -> CONVERGED before synthesis is not in ALLOWED"
                )
            else:
                state = ProjectState.CONVERGED
        for step_spec in steps:
            target = (ProjectState.SYNTHESIZING if (phase_name == "synthesis" and step_spec.step == "specialist_pipeline") else STEP_TARGET_STATE.get(step_spec.step))
            if target is None:
                continue
            if target != state:
                if target not in ALLOWED.get(state, set()):
                    errs.append(
                        f"illegal state transition {state.value} -> {target.value} at step '{step_spec.step}' in loop.{phase_name}"
                    )
                state = target
            if step_spec.pause_after or step_spec.step == "ask_user":
                if ProjectState.PAUSED not in ALLOWED.get(state, set()):
                    errs.append(
                        f"step '{step_spec.step}' with pause_after cannot transition from {state.value} to PAUSED"
                    )
                elif state not in ALLOWED.get(ProjectState.PAUSED, set()):
                    errs.append(
                        f"step '{step_spec.step}' with pause_after cannot resume from PAUSED back to {state.value}"
                    )
    return errs


def validate_manifest(
    manifest: EngineManifest,
    pack_dir: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Run all 15 static validation checks on an EngineManifest.

    Returns (errors, warnings).
    """
    from research_engine.pipeline.routing import LEG_NAMES, _MAX_LEGS
    from research_engine.prompts.registry import TEMPLATES_DIR, _sorted_versions

    errors: list[str] = []
    warnings: list[str] = []

    if manifest.schema_version != 1:
        errors.append(f"unsupported schema_version {manifest.schema_version!r}; expected 1")
    if not _ENGINE_NAME_RE.match(manifest.name):
        errors.append(f"invalid engine name {manifest.name!r}; must match ^[a-z][a-z0-9_]{{1,31}}$")

    # 1. Safety locks (INV-031, INV-034)
    if manifest.safety.allow_skip_quote_verification:
        errors.append("safety.allow_skip_quote_verification cannot be True (locked by INV-005/INV-031)")
    if manifest.safety.allow_skip_claim_support:
        errors.append("safety.allow_skip_claim_support cannot be True (locked by INV-005/INV-031)")
    if manifest.safety.allow_network_in_local_only:
        errors.append("safety.allow_network_in_local_only cannot be True (locked by INV-027/INV-031)")
    if not manifest.extraction.require_verbatim_quote:
        errors.append("extraction.require_verbatim_quote must be True (locked by INV-005/INV-031)")
    if not manifest.extraction.require_claim_support:
        errors.append("extraction.require_claim_support must be True (locked by INV-005/INV-031)")
    if (
        manifest.analysis.specialist_pipeline == "startup" or manifest.name == "startup"
    ) and not manifest.safety.require_counterevidence_for_opportunities:
        errors.append(
            "safety.require_counterevidence_for_opportunities must be True for startup engine (locked by INV-034)"
        )

    # 2. Categories & routes
    seen_cats: set[str] = set()
    if not manifest.planning.branches:
        errors.append("planning.branches must contain at least one branch specification")
    for b in manifest.planning.branches:
        if not _CATEGORY_NAME_RE.match(b.category):
            errors.append(f"invalid branch category {b.category!r}; must match ^[A-Z][A-Z0-9_]{{1,31}}$")
        if b.category in seen_cats:
            errors.append(f"duplicate branch category {b.category!r}")
        seen_cats.add(b.category)
        if not b.route:
            errors.append(f"branch {b.category!r} route must not be empty")
        if len(b.route) > _MAX_LEGS:
            errors.append(
                f"branch {b.category!r} route has {len(b.route)} legs; max allowed is {_MAX_LEGS}"
            )
        for leg in b.route:
            if leg not in LEG_NAMES:
                errors.append(
                    f"branch {b.category!r} references unknown route leg {leg!r}; valid legs: {sorted(LEG_NAMES)}"
                )
    for sp in manifest.planning.source_preferences:
        if sp not in LEG_NAMES:
            errors.append(f"planning.source_preferences contains unknown leg {sp!r}")

    # 3. Structural checks & specialist
    for chk in manifest.analysis.structural_checks:
        if chk not in STRUCTURAL_CHECK_REGISTRY:
            errors.append(
                f"unknown structural check {chk!r}; valid: {sorted(STRUCTURAL_CHECK_REGISTRY)}"
            )
    if (
        manifest.analysis.specialist_pipeline is not None
        and manifest.analysis.specialist_pipeline not in SPECIALIST_REGISTRY
    ):
        errors.append(
            f"unknown specialist_pipeline {manifest.analysis.specialist_pipeline!r}; valid: {sorted(SPECIALIST_REGISTRY)}"
        )

    # 4. Loop steps & mandatory order (INV-031)
    for phase_name, valid_set, steps in (
        ("setup", SETUP_STEPS, manifest.loop.setup),
        ("per_iteration", ITERATION_STEPS, manifest.loop.per_iteration),
        ("synthesis", SYNTHESIS_STEPS, manifest.loop.synthesis),
    ):
        for s in steps:
            if s.step not in STEP_REGISTRY:
                errors.append(f"unknown step {s.step!r} in loop.{phase_name}")
            elif s.step not in valid_set:
                errors.append(f"step {s.step!r} is not allowed in loop.{phase_name}")

    iter_names = [s.step for s in manifest.loop.per_iteration]
    if "extract_evidence" not in iter_names:
        errors.append("loop.per_iteration must include 'extract_evidence'")
    if "verify_and_dedup" not in iter_names:
        errors.append("loop.per_iteration must include 'verify_and_dedup'")
    for idx, step_name in enumerate(iter_names):
        if step_name == "extract_evidence":
            if idx + 1 >= len(iter_names) or iter_names[idx + 1] != "verify_and_dedup":
                errors.append(
                    "mandatory step order violated: 'extract_evidence' must be immediately followed by 'verify_and_dedup' (INV-031)"
                )
    synth_names = [s.step for s in manifest.loop.synthesis]
    if "write_reports" not in synth_names:
        errors.append("loop.synthesis must include 'write_reports'")

    # 5. State transition walk
    if not errors:
        errors.extend(_simulate_state_walk(manifest))

    # 6. Stop conditions & metric registry
    for cond in manifest.loop.stop_when:
        if cond.metric not in METRIC_REGISTRY:
            errors.append(
                f"stop_when references unknown metric {cond.metric!r}; valid: {sorted(METRIC_REGISTRY)}"
            )
        if cond.op not in STOP_OPS:
            errors.append(f"stop_when references invalid operator {cond.op!r}; valid: {sorted(STOP_OPS)}")
        if cond.after_iteration < 1:
            errors.append(f"stop_when after_iteration must be >= 1, got {cond.after_iteration}")

    # 7. Reports registry
    for cfile in manifest.reports.core:
        if cfile not in CORE_REPORT_FILES:
            errors.append(f"unknown core report file {cfile!r}; valid: {sorted(CORE_REPORT_FILES)}")
    for drep in manifest.reports.domain:
        if drep.id not in DOMAIN_REPORT_REGISTRY:
            errors.append(f"unknown domain report id {drep.id!r}")
    for irep in manifest.reports.intelligence:
        if irep.id not in INTELLIGENCE_REPORT_REGISTRY:
            errors.append(f"unknown intelligence report id {irep.id!r}")
    for rrep in manifest.reports.reasoning:
        if rrep.id not in REASONING_REPORT_REGISTRY:
            errors.append(f"unknown reasoning report id {rrep.id!r}")

    # 8. Prompt template existence & placeholder validation
    for role_label, tmpl_name in (
        ("clarifier", manifest.clarifier.prompt_template),
        ("extraction", manifest.extraction.prompt_template),
    ):
        pack_tmpl_dir = (pack_dir / "prompts" / tmpl_name) if pack_dir else None
        sys_tmpl_dir = TEMPLATES_DIR / tmpl_name
        chosen_dir = (
            pack_tmpl_dir
            if (pack_tmpl_dir and pack_tmpl_dir.is_dir() and _sorted_versions(pack_tmpl_dir))
            else sys_tmpl_dir
        )
        if not chosen_dir.is_dir() or not _sorted_versions(chosen_dir):
            errors.append(f"{role_label}.prompt_template {tmpl_name!r} not found")
            continue
        latest_ver = _sorted_versions(chosen_dir)[-1]
        txt = (chosen_dir / f"{latest_ver}.txt").read_text(encoding="utf-8")
        placeholders = {m.group(1) for m in _PLACEHOLDER_RE.finditer(txt)}
        allowed_kwargs = PROMPT_CALLER_KWARGS.get(tmpl_name)
        if allowed_kwargs is not None:
            unknown_ph = placeholders - allowed_kwargs
            if unknown_ph:
                errors.append(
                    f"prompt template {tmpl_name!r} ({latest_ver}) uses unsupported placeholders: {sorted(unknown_ph)}"
                )

    # Also validate any additional custom prompts in pack_dir/prompts/
    if pack_dir and (pack_dir / "prompts").is_dir():
        for pdir in sorted((pack_dir / "prompts").iterdir()):
            if not pdir.is_dir():
                continue
            vers = _sorted_versions(pdir)
            if not vers:
                errors.append(f"pack prompt directory '{pdir.name}' contains no vN.txt files")
                continue
            allowed_kwargs = PROMPT_CALLER_KWARGS.get(pdir.name)
            if allowed_kwargs is not None:
                for v in vers:
                    txt = (pdir / f"{v}.txt").read_text(encoding="utf-8")
                    placeholders = {m.group(1) for m in _PLACEHOLDER_RE.finditer(txt)}
                    unknown_ph = placeholders - allowed_kwargs
                    if unknown_ph:
                        errors.append(
                            f"pack prompt '{pdir.name}/{v}.txt' uses unsupported placeholders: {sorted(unknown_ph)}"
                        )

    # 9. Domain schema validation
    if manifest.extraction.domain_schema and pack_dir is not None:
        try:
            _, schema_warnings = load_domain_schema(pack_dir, manifest.extraction.domain_schema)
            warnings.extend(schema_warnings)
        except DomainSchemaError as exc:
            errors.append(str(exc))

    # 10. Tunables bounds
    errors.extend(_validate_tunables_bounds(manifest.tunables))

    return errors, warnings


def load_engine_from_dir(
    pack_dir: str | Path,
    workspace_dir: str | Path | None = None,
) -> EngineManifest:
    """Load, resolve inheritance, and validate an engine pack from a directory or path."""
    discovered = discover_engine_dirs(workspace_dir)
    raw, resolved_dir, layer = _load_raw_with_Inheritance(Path(pack_dir), discovered)
    try:
        manifest = EngineManifest.model_validate(raw)
    except ValidationError as exc:
        msgs = [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise EngineValidationError(msgs) from exc

    errors, _warnings = validate_manifest(manifest, resolved_dir)
    if errors:
        raise EngineValidationError(errors, _warnings)

    manifest.pack_dir = str(resolved_dir)
    manifest.source_layer = layer
    manifest.skills = load_pack_skills(resolved_dir)
    if manifest.extraction.domain_schema:
        schema_dict, _ = load_domain_schema(resolved_dir, manifest.extraction.domain_schema)
        manifest.domain_schema_dict = schema_dict
    return manifest


def get_engine(
    name: str,
    workspace_dir: str | Path | None = None,
) -> EngineManifest:
    """Return a validated EngineManifest by name."""
    ws_key = str(Path(workspace_dir).resolve()) if workspace_dir else ""
    cache_key = (name, ws_key)
    if cache_key in _ENGINE_CACHE:
        return _ENGINE_CACHE[cache_key]

    discovered = discover_engine_dirs(workspace_dir)
    raw, resolved_dir, layer = _load_raw_with_Inheritance(name, discovered)
    try:
        manifest = EngineManifest.model_validate(raw)
    except ValidationError as exc:
        msgs = [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise EngineValidationError(msgs) from exc

    errors, _warnings = validate_manifest(manifest, resolved_dir)
    if errors:
        raise EngineValidationError(errors, _warnings)

    manifest.pack_dir = str(resolved_dir)
    manifest.source_layer = layer
    manifest.skills = load_pack_skills(resolved_dir)
    if manifest.extraction.domain_schema:
        schema_dict, _ = load_domain_schema(resolved_dir, manifest.extraction.domain_schema)
        manifest.domain_schema_dict = schema_dict

    _ENGINE_CACHE[cache_key] = manifest
    return manifest


def validate_engine_target(
    name_or_path: str | Path,
    workspace_dir: str | Path | None = None,
) -> tuple[EngineManifest, list[str]]:
    """Validate an engine by name or directory path; returns (manifest, warnings) or raises EngineValidationError."""
    discovered = discover_engine_dirs(workspace_dir)
    p = Path(name_or_path)
    target: str | Path = p if (p.exists() or "/" in str(name_or_path)) else str(name_or_path)
    raw, resolved_dir, layer = _load_raw_with_Inheritance(target, discovered)
    try:
        manifest = EngineManifest.model_validate(raw)
    except ValidationError as exc:
        msgs = [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise EngineValidationError(msgs) from exc
    errors, warnings = validate_manifest(manifest, resolved_dir)
    if errors:
        raise EngineValidationError(errors, warnings)
    manifest.pack_dir = str(resolved_dir)
    manifest.source_layer = layer
    manifest.skills = load_pack_skills(resolved_dir)
    if manifest.extraction.domain_schema:
        schema_dict, _ = load_domain_schema(resolved_dir, manifest.extraction.domain_schema)
        manifest.domain_schema_dict = schema_dict
    return manifest, warnings


# ------------------------------------------------------------------ 6-layer effective config (Phase 4)

_TUNABLE_TO_CONFIG_PATH: dict[str, tuple[str, str]] = {
    "max_iterations": ("research", "max_iterations"),
    "max_queries_per_iteration": ("research", "max_queries_per_iteration"),
    "max_documents": ("research", "max_documents"),
    "max_sources_total": ("research", "max_sources_total"),
    "max_llm_calls": ("research", "max_llm_calls"),
    "max_wall_clock_minutes": ("research", "max_wall_clock_minutes"),
    "new_evidence_threshold": ("research", "new_evidence_threshold"),
    "duplicate_rate_converged": ("research", "duplicate_rate_converged"),
    "review_gates_enabled": ("research", "review_gates_enabled"),
    "results_per_query": ("search", "results_per_query"),
    "max_chunk_chars": ("resources", "max_chunk_chars"),
    "chunk_overlap_chars": ("resources", "chunk_overlap_chars"),
}


def parse_cli_set_overrides(pairs: list[str] | None) -> dict[str, Any]:
    """Parse --set key=value pairs into a nested dict or flat tunable map."""
    out: dict[str, Any] = {}
    for item in pairs or []:
        if "=" not in item:
            raise ValueError(f"invalid --set argument {item!r}; expected key=value")
        k, v = item.split("=", 1)
        k = k.strip()
        v_str = v.strip()
        if v_str.lower() in ("true", "false"):
            val: Any = v_str.lower() == "true"
        else:
            try:
                val = int(v_str)
            except ValueError:
                try:
                    val = float(v_str)
                except ValueError:
                    val = v_str
        out[k] = val
    return out


def resolve_effective_config(
    base_cfg: AppConfig,
    engine: EngineManifest | str,
    project_workspace: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> tuple[AppConfig, dict[str, dict[str, Any]]]:
    """Resolve the 6-layer effective configuration for a project run.

    Precedence (lowest to highest):
    1. Built-in AppConfig defaults
    2. Engine pack tunables (engine.yaml)
    3. User gar.yaml (only fields explicitly set on base_cfg via model_fields_set)
    4. GAR_* environment variables
    5. Project workspace overrides.yaml (<project_workspace>/overrides.yaml)
    6. CLI --set key=value overrides

    Returns (effective_cfg, provenance_by_key).
    """
    manifest = get_engine(engine) if isinstance(engine, str) else engine
    eff = AppConfig()
    eff.models = copy.deepcopy(base_cfg.models)
    eff.network = copy.deepcopy(base_cfg.network)
    eff.storage = copy.deepcopy(base_cfg.storage)
    eff.embeddings = copy.deepcopy(base_cfg.embeddings)
    eff.platform = copy.deepcopy(base_cfg.platform)
    eff.search = copy.deepcopy(base_cfg.search)
    eff.resources = copy.deepcopy(base_cfg.resources)
    eff.research = copy.deepcopy(base_cfg.research)
    eff.research.mode = manifest.name

    provenance: dict[str, dict[str, Any]] = {}
    defaults_cfg = AppConfig()

    # Layer 1: Built-in defaults
    for t_key, (sec, fld) in _TUNABLE_TO_CONFIG_PATH.items():
        val = getattr(getattr(defaults_cfg, sec), fld)
        setattr(getattr(eff, sec), fld, val)
        provenance[f"{sec}.{fld}"] = {"value": val, "source": "1:builtin_default"}

    for extra_t in ("ask_user_enabled", "ask_user_blocking", "max_user_questions_per_run"):
        default_v = getattr(TunablesSpec(), extra_t)
        provenance[f"tunables.{extra_t}"] = {"value": default_v, "source": "1:builtin_default"}

    # Layer 2: Engine pack tunables
    for t_key, (sec, fld) in _TUNABLE_TO_CONFIG_PATH.items():
        t_val = getattr(manifest.tunables, t_key)
        if t_val is not None:
            setattr(getattr(eff, sec), fld, t_val)
            provenance[f"{sec}.{fld}"] = {"value": t_val, "source": f"2:engine({manifest.name})"}

    for extra_t in ("ask_user_enabled", "ask_user_blocking", "max_user_questions_per_run"):
        if extra_t in getattr(manifest.tunables, "model_fields_set", getattr(manifest.tunables, "__fields_set__", set())):
            t_val = getattr(manifest.tunables, extra_t)
            provenance[f"tunables.{extra_t}"] = {"value": t_val, "source": f"2:engine({manifest.name})"}

    # Layer 3: User gar.yaml / explicit fields set on base_cfg
    for t_key, (sec, fld) in _TUNABLE_TO_CONFIG_PATH.items():
        sec_obj = getattr(base_cfg, sec)
        if fld in getattr(sec_obj, "model_fields_set", getattr(sec_obj, "__fields_set__", set())):
            u_val = getattr(sec_obj, fld)
            setattr(getattr(eff, sec), fld, u_val)
            provenance[f"{sec}.{fld}"] = {"value": u_val, "source": "3:gar.yaml"}

    # Layer 4: GAR_* environment variables
    for t_key, (sec, fld) in _TUNABLE_TO_CONFIG_PATH.items():
        env_name = f"GAR_{sec.upper()}__{fld.upper()}"
        if env_name in os.environ:
            sec_model = getattr(eff, sec)
            ann = type(sec_model).model_fields[fld].annotation
            coerced = _coerce_env_value(os.environ[env_name], ann, env_name, f"{sec}.{fld}")
            setattr(sec_model, fld, coerced)
            provenance[f"{sec}.{fld}"] = {"value": coerced, "source": f"4:env({env_name})"}

    # Layer 5: Per-project <workspace>/overrides.yaml
    if project_workspace:
        ov_path = Path(project_workspace) / "overrides.yaml"
        if ov_path.is_file():
            ov_data = yaml.safe_load(ov_path.read_text(encoding="utf-8")) or {}
            if isinstance(ov_data, dict):
                _apply_override_dict(eff, provenance, ov_data, "5:overrides.yaml")

    # Layer 6: CLI --set overrides
    if cli_overrides:
        _apply_override_dict(eff, provenance, cli_overrides, "6:cli(--set)")

    # Validate final effective bounds
    final_tunables = TunablesSpec(
        max_iterations=eff.research.max_iterations,
        max_queries_per_iteration=eff.research.max_queries_per_iteration,
        max_documents=eff.research.max_documents,
        max_sources_total=eff.research.max_sources_total,
        max_llm_calls=eff.research.max_llm_calls,
        max_wall_clock_minutes=eff.research.max_wall_clock_minutes,
        new_evidence_threshold=eff.research.new_evidence_threshold,
        duplicate_rate_converged=eff.research.duplicate_rate_converged,
        results_per_query=eff.search.results_per_query,
        max_chunk_chars=eff.resources.max_chunk_chars,
        chunk_overlap_chars=eff.resources.chunk_overlap_chars,
        review_gates_enabled=eff.research.review_gates_enabled,
        ask_user_enabled=bool(provenance["tunables.ask_user_enabled"]["value"]),
        ask_user_blocking=bool(provenance["tunables.ask_user_blocking"]["value"]),
        max_user_questions_per_run=int(provenance["tunables.max_user_questions_per_run"]["value"]),
    )
    bound_errors = _validate_tunables_bounds(final_tunables)
    if bound_errors:
        raise EngineValidationError(bound_errors)

    return eff, provenance


def _apply_override_dict(
    eff: AppConfig,
    provenance: dict[str, dict[str, Any]],
    overrides: dict[str, Any],
    source_label: str,
) -> None:
    flat: dict[str, Any] = {}
    for k, v in overrides.items():
        if isinstance(v, dict):
            for sub_k, sub_v in v.items():
                flat[f"{k}.{sub_k}"] = sub_v
        else:
            flat[k] = v

    for raw_k, val in flat.items():
        if raw_k in _TUNABLE_TO_CONFIG_PATH:
            sec, fld = _TUNABLE_TO_CONFIG_PATH[raw_k]
            setattr(getattr(eff, sec), fld, val)
            provenance[f"{sec}.{fld}"] = {"value": val, "source": source_label}
        elif raw_k in ("ask_user_enabled", "ask_user_blocking", "max_user_questions_per_run"):
            provenance[f"tunables.{raw_k}"] = {"value": val, "source": source_label}
        elif "." in raw_k:
            sec, fld = raw_k.split(".", 1)
            if sec == "tunables" and fld in _TUNABLE_TO_CONFIG_PATH:
                s2, f2 = _TUNABLE_TO_CONFIG_PATH[fld]
                setattr(getattr(eff, s2), f2, val)
                provenance[f"{s2}.{f2}"] = {"value": val, "source": source_label}
            elif sec == "tunables" and fld in ("ask_user_enabled", "ask_user_blocking", "max_user_questions_per_run"):
                provenance[f"tunables.{fld}"] = {"value": val, "source": source_label}
            elif hasattr(eff, sec) and hasattr(getattr(eff, sec), fld):
                setattr(getattr(eff, sec), fld, val)
                provenance[f"{sec}.{fld}"] = {"value": val, "source": source_label}
            else:
                raise EngineValidationError([f"unknown override key '{raw_k}' in {source_label}"])
        else:
            raise EngineValidationError([f"unknown override key '{raw_k}' in {source_label}"])


def explain_engine(
    name: str,
    cfg: AppConfig | None = None,
    project_workspace: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
    include_vars: bool = False,
) -> dict[str, Any]:
    """Produce a structured explanation of an engine's configuration, loop, prompts, and provenance."""
    from research_engine.prompts.registry import get_prompt

    base_cfg = cfg or AppConfig()
    manifest = get_engine(name, workspace_dir=project_workspace)
    eff_cfg, provenance = resolve_effective_config(
        base_cfg, manifest, project_workspace=project_workspace, cli_overrides=cli_overrides
    )

    out: dict[str, Any] = {
        "name": manifest.name,
        "display_name": manifest.display_name,
        "version": manifest.version,
        "extends": manifest.extends,
        "source_layer": manifest.source_layer,
        "pack_dir": manifest.pack_dir,
        "categories": manifest.branch_categories(),
        "routes": manifest.routes_by_category(),
        "structural_checks": list(manifest.analysis.structural_checks),
        "specialist_pipeline": manifest.analysis.specialist_pipeline,
        "loop": {
            "setup": [s.model_dump() for s in manifest.loop.setup],
            "per_iteration": [s.model_dump() for s in manifest.loop.per_iteration],
            "stop_when": [c.model_dump() for c in manifest.loop.stop_when],
            "synthesis": [s.model_dump() for s in manifest.loop.synthesis],
        },
        "reports": manifest.reports.model_dump(),
        "effective_config": provenance,
        "skills_loaded": [s.name for s in manifest.skills],
    }
    if include_vars:
        c_spec = get_prompt(manifest.clarifier.prompt_template, engine=manifest.name)
        e_spec = get_prompt(manifest.extraction.prompt_template, engine=manifest.name)
        out["prompt_variables"] = {
            "clarifier": {
                "template": manifest.clarifier.prompt_template,
                "version": c_spec.version,
                "mode_hint": manifest.clarifier.hint,
                "engine_guidance": manifest.guidance_for("clarify"),
            },
            "extractor": {
                "template": manifest.extraction.prompt_template,
                "version": e_spec.version,
                "schema_hint": manifest.extraction.schema_hint,
                "domain_schema": manifest.extraction.domain_schema,
            },
        }
    return out


def diff_engines(
    name_a: str,
    name_b: str,
    workspace_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return a structured comparison between two engine packs."""
    ma = get_engine(name_a, workspace_dir=workspace_dir)
    mb = get_engine(name_b, workspace_dir=workspace_dir)
    da = json.loads(ma.model_dump_json())
    db = json.loads(mb.model_dump_json())
    diffs: dict[str, dict[str, Any]] = {}
    for key in sorted(set(da.keys()) | set(db.keys())):
        if da.get(key) != db.get(key):
            diffs[key] = {name_a: da.get(key), name_b: db.get(key)}
    return {"engine_a": name_a, "engine_b": name_b, "differences": diffs}


def scaffold_engine(
    name: str,
    target_root: Path | None = None,
    extends: str = "generic",
) -> Path:
    """Scaffold a new custom engine pack directory (`research engine new <name>`)."""
    if not _ENGINE_NAME_RE.match(name):
        raise EngineValidationError([f"invalid engine name {name!r}; must match ^[a-z][a-z0-9_]{{1,31}}$"])
    root = target_root or (Path.cwd() / "engines")
    pack_dir = root / name
    if pack_dir.exists():
        raise FileExistsError(f"engine directory already exists: {pack_dir}")
    (pack_dir / "skills").mkdir(parents=True, exist_ok=True)

    engine_yaml = {
        "schema_version": 1,
        "name": name,
        "display_name": f"{name.replace('_', ' ').title()} Research Engine",
        "version": "1.0.0",
        "description": f"Custom research engine extending '{extends}'.",
        "extends": extends,
        "clarifier": {
            "hint": f"{name.replace('_', ' ')} domain research",
            "prompt_template": "problem_clarifier",
            "required_inputs": [],
            "ask_user_when": [],
        },
        "extraction": {
            "schema_hint": "claim; quote; entities; numbers; domain attributes",
            "prompt_template": "evidence_extractor",
            "domain_schema": "schema.json",
            "require_verbatim_quote": True,
            "require_claim_support": True,
        },
    }
    (pack_dir / "engine.yaml").write_text(yaml.safe_dump(engine_yaml, sort_keys=False), encoding="utf-8")
    schema_json = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"{name.title()}EvidenceAttributes",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "subject_entity": {"type": "string"},
            "key_metric": {"type": "string"},
        },
    }
    (pack_dir / "schema.json").write_text(json.dumps(schema_json, indent=2) + "\n", encoding="utf-8")
    (pack_dir / "README.md").write_text(
        f"# {name} Engine Pack\n\nCustom GAR research engine extending `{extends}`.\n",
        encoding="utf-8",
    )
    (pack_dir / "skills" / "playbook.md").write_text(
        f"---\nphase: clarify\npriority: 50\n---\n# {name.title()} Playbook\n\nFocus on verifiable primary sources.\n",
        encoding="utf-8",
    )
    reload()
    return pack_dir
