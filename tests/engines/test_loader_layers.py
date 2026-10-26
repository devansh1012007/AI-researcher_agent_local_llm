"""Tests for engine discovery precedence, inheritance, reload, and 6-layer config resolution (Phase 1 & Phase 4)."""
from __future__ import annotations

from pathlib import Path

import yaml

from research_engine.core.config import AppConfig, ResearchConfig
from research_engine.engines.loader import (
    clear_search_dirs,
    diff_engines,
    explain_engine,
    get_engine,
    register_search_dir,
    reload,
    resolve_effective_config,
    scaffold_engine,
)
from research_engine.prompts.registry import get_prompt


def test_six_layer_config_precedence(tmp_path: Path, monkeypatch):
    """Verify Layer 1 < Layer 2 (engine.yaml) < Layer 3 (gar.yaml) < Layer 4 (env) < Layer 5 (overrides.yaml) < Layer 6 (--set)."""
    engines_dir = tmp_path / "engines"
    custom_dir = scaffold_engine("custom_pack", target_root=engines_dir, extends="generic")
    ey = yaml.safe_load((custom_dir / "engine.yaml").read_text())
    ey["tunables"] = {
        "max_iterations": 5,
        "max_queries_per_iteration": 12,
        "max_documents": 40,
        "max_sources_total": 120,
        "results_per_query": 7,
    }
    (custom_dir / "engine.yaml").write_text(yaml.safe_dump(ey))

    try:
        register_search_dir(engines_dir)
        manifest = get_engine("custom_pack")

        # Layer 1 & Layer 2 only (fresh AppConfig() has no user fields set)
        base_cfg = AppConfig()
        eff2, prov2 = resolve_effective_config(base_cfg, manifest)
        assert eff2.research.max_iterations == 5
        assert prov2["research.max_iterations"]["source"] == "2:engine(custom_pack)"
        assert eff2.search.results_per_query == 7
        assert prov2["search.results_per_query"]["source"] == "2:engine(custom_pack)"

        # Layer 3: explicit field set in gar.yaml overrides Layer 2
        cfg3 = AppConfig(research=ResearchConfig(max_iterations=6))
        eff3, prov3 = resolve_effective_config(cfg3, manifest)
        assert eff3.research.max_iterations == 6
        assert prov3["research.max_iterations"]["source"] == "3:gar.yaml"
        # Unset fields in gar.yaml still come from Layer 2!
        assert eff3.research.max_queries_per_iteration == 12
        assert prov3["research.max_queries_per_iteration"]["source"] == "2:engine(custom_pack)"

        # Layer 4: GAR_RESEARCH__MAX_ITERATIONS env var overrides Layer 3
        monkeypatch.setenv("GAR_RESEARCH__MAX_ITERATIONS", "7")
        eff4, prov4 = resolve_effective_config(cfg3, manifest)
        assert eff4.research.max_iterations == 7
        assert prov4["research.max_iterations"]["source"] == "4:env(GAR_RESEARCH__MAX_ITERATIONS)"

        # Layer 5: per-project <workspace>/overrides.yaml overrides Layer 4
        proj_ws = tmp_path / "proj_test"
        proj_ws.mkdir()
        (proj_ws / "overrides.yaml").write_text(yaml.safe_dump({"max_iterations": 8}))
        eff5, prov5 = resolve_effective_config(cfg3, manifest, project_workspace=proj_ws)
        assert eff5.research.max_iterations == 8
        assert prov5["research.max_iterations"]["source"] == "5:overrides.yaml"

        # Layer 6: CLI --set overrides Layer 5
        eff6, prov6 = resolve_effective_config(
            cfg3, manifest, project_workspace=proj_ws, cli_overrides={"max_iterations": 9}
        )
        assert eff6.research.max_iterations == 9
        assert prov6["research.max_iterations"]["source"] == "6:cli(--set)"
    finally:
        clear_search_dirs()


def test_explain_and_diff_engines():
    exp = explain_engine("academic", include_vars=True)
    assert exp["name"] == "academic"
    assert "FOUNDATIONS" in exp["categories"]
    assert "prompt_variables" in exp
    assert exp["prompt_variables"]["clarifier"]["template"] == "problem_clarifier"

    diff = diff_engines("academic", "startup")
    assert diff["engine_a"] == "academic"
    assert diff["engine_b"] == "startup"
    assert "planning" in diff["differences"]
    assert "analysis" in diff["differences"]


def test_reload_invalidates_prompt_overlay_cache(tmp_path: Path):
    engines_dir = tmp_path / "engines"
    pack_dir = scaffold_engine("overlay_pack", target_root=engines_dir, extends="generic")
    pdir = pack_dir / "prompts" / "problem_clarifier"
    pdir.mkdir(parents=True)
    (pdir / "v1.txt").write_text("V1 OVERLAY: {{raw_question}} ({{mode}}: {{mode_hint}}) {{engine_guidance}}")
    (pdir / "v1.meta.yaml").write_text("system: overlay v1\n")

    try:
        register_search_dir(engines_dir)
        s1 = get_prompt("problem_clarifier", engine="overlay_pack")
        assert "V1 OVERLAY" in s1.template

        (pdir / "v1.txt").write_text("V1 UPDATED: {{raw_question}} ({{mode}}: {{mode_hint}}) {{engine_guidance}}")
        reload()
        s2 = get_prompt("problem_clarifier", engine="overlay_pack")
        assert "V1 UPDATED" in s2.template
    finally:
        clear_search_dirs()
