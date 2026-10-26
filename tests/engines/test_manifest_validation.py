"""Static validation tests for EngineManifest (Phase 1, Phase 3, Phase 7, INV-031, INV-034, INV-035)."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from research_engine.core.config import AppConfig
from research_engine.core.orchestrator import Orchestrator
from research_engine.engines.loader import (
    EngineValidationError,
    get_engine,
    load_engine_from_dir,
    register_search_dir,
    clear_search_dirs,
    validate_manifest,
)
from research_engine.engines.manifest import EngineManifest
from research_engine.engines.registry import METRIC_REGISTRY
from research_engine.models.project import ResearchMetrics


def _base_manifest_dict() -> dict:
    return json.loads(get_engine("generic").model_dump_json())


def test_builtin_engines_all_validate_cleanly():
    for name in ("academic", "startup", "generic"):
        m = get_engine(name)
        errs, warnings = validate_manifest(m, Path(m.pack_dir))
        assert errs == []
        assert warnings == []


def test_every_metric_in_registry_maps_to_populated_research_metrics(tmp_path: Path):
    """Phase 3: prove every metric in METRIC_REGISTRY is populated by Orchestrator._compute_metrics."""
    cfg = AppConfig()
    cfg.storage.data_dir = str(tmp_path / "data")
    orch = Orchestrator.create_project(cfg, "Does metric registry match ResearchMetrics fields?", mode="academic")
    computed = orch._compute_metrics(1)
    model_fields = set(ResearchMetrics.model_fields.keys())
    for metric_name in METRIC_REGISTRY:
        assert metric_name in model_fields, f"{metric_name} missing from ResearchMetrics"
        val = getattr(computed, metric_name)
        assert isinstance(val, (int, float)), f"{metric_name} on computed ResearchMetrics is {type(val)}"


def test_mandatory_step_order_enforced_inv_031():
    raw = _base_manifest_dict()
    # Swap extract_evidence and verify_and_dedup
    raw["loop"]["per_iteration"] = [
        {"step": "search"},
        {"step": "fetch_and_parse"},
        {"step": "verify_and_dedup"},
        {"step": "extract_evidence"},
        {"step": "evaluate_convergence"},
    ]
    m = EngineManifest.model_validate(raw)
    errs, _ = validate_manifest(m)
    assert any("mandatory step order violated" in e for e in errs)

    # Remove write_reports from synthesis
    raw2 = _base_manifest_dict()
    raw2["loop"]["synthesis"] = []
    m2 = EngineManifest.model_validate(raw2)
    errs2, _ = validate_manifest(m2)
    assert any("write_reports" in e for e in errs2)


def test_safety_locks_cannot_be_disabled_inv_031_inv_034():
    for field_name in (
        "allow_skip_quote_verification",
        "allow_skip_claim_support",
        "allow_network_in_local_only",
    ):
        raw = _base_manifest_dict()
        raw["safety"][field_name] = True
        m = EngineManifest.model_validate(raw)
        errs, _ = validate_manifest(m)
        assert any(field_name in e for e in errs), f"Expected error for safety.{field_name}=True"

    for ext_field in ("require_verbatim_quote", "require_claim_support"):
        raw = _base_manifest_dict()
        raw["extraction"][ext_field] = False
        m = EngineManifest.model_validate(raw)
        errs, _ = validate_manifest(m)
        assert any(ext_field in e for e in errs)

    # Startup counterevidence lock (INV-034)
    raw_st = json.loads(get_engine("startup").model_dump_json())
    raw_st["safety"]["require_counterevidence_for_opportunities"] = False
    m_st = EngineManifest.model_validate(raw_st)
    errs_st, _ = validate_manifest(m_st)
    assert any("require_counterevidence_for_opportunities" in e for e in errs_st)


def test_unknown_route_leg_and_excess_legs_rejected():
    raw = _base_manifest_dict()
    raw["planning"]["branches"][0]["route"] = ["web", "nonexistent_provider"]
    m = EngineManifest.model_validate(raw)
    errs, _ = validate_manifest(m)
    assert any("unknown route leg 'nonexistent_provider'" in e for e in errs)

    raw2 = _base_manifest_dict()
    raw2["planning"]["branches"][0]["route"] = ["web", "openalex", "arxiv", "crossref", "forum"]
    m2 = EngineManifest.model_validate(raw2)
    errs2, _ = validate_manifest(m2)
    assert any("max allowed is 4" in e for e in errs2)


def test_unknown_structural_check_and_metric_rejected():
    raw = _base_manifest_dict()
    raw["analysis"]["structural_checks"].append("not_a_real_check")
    raw["loop"]["stop_when"].append({"metric": "fake_metric", "op": "<=", "value": 0.5, "after_iteration": 1})
    m = EngineManifest.model_validate(raw)
    errs, _ = validate_manifest(m)
    assert any("unknown structural check 'not_a_real_check'" in e for e in errs)
    assert any("unknown metric 'fake_metric'" in e for e in errs)


def test_tunables_bounds_validated():
    raw = _base_manifest_dict()
    raw["tunables"]["max_iterations"] = 0
    raw["tunables"]["chunk_overlap_chars"] = 7000
    raw["tunables"]["max_chunk_chars"] = 6000
    raw["tunables"]["max_documents"] = 200
    raw["tunables"]["max_sources_total"] = 100
    m = EngineManifest.model_validate(raw)
    errs, _ = validate_manifest(m)
    assert any("max_iterations" in e for e in errs)
    assert any("chunk_overlap_chars" in e for e in errs)
    assert any("max_documents" in e for e in errs)


def test_domain_schema_rejects_remote_ref_and_warns_above_8_fields(tmp_path: Path):
    pack = tmp_path / "bad_schema_pack"
    pack.mkdir()
    raw = _base_manifest_dict()
    raw["name"] = "bad_schema_pack"
    raw["extraction"]["domain_schema"] = "schema.json"
    (pack / "engine.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    (pack / "schema.json").write_text(
        json.dumps({
            "type": "object",
            "properties": {
                "evil": {"$ref": "https://attacker.example.com/schema.json"}
            },
        }),
        encoding="utf-8",
    )
    with pytest.raises(EngineValidationError, match="forbidden \\$ref"):
        load_engine_from_dir(pack)

    # Now test >8 properties emits warning but succeeds
    props = {f"field_{i}": {"type": "string"} for i in range(9)}
    (pack / "schema.json").write_text(
        json.dumps({"type": "object", "properties": props}),
        encoding="utf-8",
    )
    m = load_engine_from_dir(pack)
    _, warnings = validate_manifest(m, pack)
    assert any("9 properties" in w for w in warnings)


def test_extends_cycle_and_depth_limit_rejected(tmp_path: Path):
    engines_root = tmp_path / "engines"
    engines_root.mkdir()
    try:
        register_search_dir(engines_root)
        # 2-node cycle: cyc_a <-> cyc_b
        for name, parent in (("cyc_a", "cyc_b"), ("cyc_b", "cyc_a")):
            d = engines_root / name
            d.mkdir()
            (d / "engine.yaml").write_text(
                yaml.safe_dump({"schema_version": 1, "name": name, "display_name": name, "extends": parent}),
                encoding="utf-8",
            )
        with pytest.raises(EngineValidationError, match="cycle"):
            get_engine("cyc_a")

        # Depth > 2: d1 -> d2 -> d3 -> generic
        for name, parent in (("d3", "generic"), ("d2", "d3"), ("d1", "d2")):
            d = engines_root / name
            d.mkdir()
            (d / "engine.yaml").write_text(
                yaml.safe_dump({"schema_version": 1, "name": name, "display_name": name, "extends": parent}),
                encoding="utf-8",
            )
        with pytest.raises(EngineValidationError, match="depth exceeds maximum of 2"):
            get_engine("d1")
    finally:
        clear_search_dirs()


def test_prompt_template_unknown_placeholder_rejected(tmp_path: Path):
    pack = tmp_path / "bad_prompt_pack"
    pdir = pack / "prompts" / "problem_clarifier"
    pdir.mkdir(parents=True)
    raw = _base_manifest_dict()
    raw["name"] = "bad_prompt_pack"
    (pack / "engine.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    (pdir / "v1.txt").write_text("Question: {{raw_question}} {{nonexistent_placeholder}}", encoding="utf-8")
    (pdir / "v1.meta.yaml").write_text("system: test\n", encoding="utf-8")
    with pytest.raises(EngineValidationError, match="nonexistent_placeholder"):
        load_engine_from_dir(pack)
