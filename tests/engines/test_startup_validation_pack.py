"""Structure, locks and packaging of the built-in startup_validation engine pack."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from research_engine.engines import loader
from research_engine.engines.manifest import EngineValidationError
from research_engine.engines.skills import MAX_SKILLS_CHARS, load_pack_skills, render_skills_guidance

PACK = Path(loader.__file__).parent / "builtin" / "startup_validation"


def test_pack_loads_with_no_errors_and_distinct_from_startup():
    m = loader.get_engine("startup_validation")
    assert m.analysis.specialist_pipeline == "startup_validation"
    assert loader.get_engine("startup").analysis.specialist_pipeline == "startup"
    assert "startup_validation" in [e.name for e in loader.list_engines()]


def test_every_branch_category_is_known_and_covers_falsification():
    m = loader.get_engine("startup_validation")
    cats = {b.category for b in m.planning.branches}
    assert {"PAIN", "ALTERNATIVES", "PRICING", "COMPETITORS", "RISKS"} <= cats
    risks = next(b for b in m.planning.branches if b.category == "RISKS")
    assert risks.fallback, "the failure/counterevidence branch must survive an unusable plan"
    assert "FUNDING" not in cats, "investor hype is not validation evidence"


def test_demand_and_counterevidence_branches_outrank_market_size():
    imp = {b.category: b.importance for b in loader.get_engine("startup_validation").planning.branches}
    assert imp["PAIN"] > imp["MARKET"] and imp["RISKS"] > imp["MARKET"]


def test_schema_stays_small_and_has_stance():
    schema = json.loads((PACK / "schema.json").read_text())
    assert len(schema["properties"]) <= 8
    assert "stance_on_idea" in schema["properties"]


def test_skills_fit_the_context_budget_for_every_phase():
    skills = load_pack_skills(PACK)
    assert {s.phase for s in skills} >= {"all", "clarify", "plan", "extract", "synthesize"}
    for phase in ("clarify", "plan", "extract", "synthesize"):
        assert len(render_skills_guidance(skills, phase)) <= MAX_SKILLS_CHARS
    # a small local model has ~8k tokens of context: keep the whole pack well under 1 phase's cap
    assert sum(len(s.body) for s in skills) < 2 * MAX_SKILLS_CHARS


@pytest.mark.parametrize("field,value", [
    ("require_counterevidence_for_opportunities", False),
    ("allow_skip_quote_verification", True),
    ("allow_skip_claim_support", True),
    ("allow_network_in_local_only", True),
])
def test_locks_cannot_be_disabled_in_a_copy_of_the_pack(tmp_path, field, value):
    dst = tmp_path / "startup_validation"
    shutil.copytree(PACK, dst)
    raw = yaml.safe_load((dst / "engine.yaml").read_text())
    raw["safety"][field] = value
    (dst / "engine.yaml").write_text(yaml.safe_dump(raw))
    with pytest.raises(EngineValidationError) as exc:
        loader.validate_engine_target(str(dst))
    assert "locked" in str(exc.value).lower() or "INV-0" in str(exc.value)


def test_loop_is_the_canonical_loop_so_it_stays_valid_when_the_loop_becomes_executable():
    a, b = loader.get_engine("startup"), loader.get_engine("startup_validation")
    assert [s.step for s in a.loop.per_iteration] == [s.step for s in b.loop.per_iteration]
    assert [s.step for s in a.loop.synthesis] == [s.step for s in b.loop.synthesis]


def test_pack_files_are_covered_by_package_data():
    """check_dist builds a real wheel; this is the cheap in-tree equivalent."""
    import glob
    import tomllib
    root = Path(__file__).resolve().parents[2]
    patterns = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["setuptools"][
        "package-data"]["research_engine.engines"]
    base = root / "src" / "research_engine" / "engines"
    covered = {Path(p) for pat in patterns for p in glob.glob(str(base / pat), recursive=True)}
    files = {p for p in PACK.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    assert files and files <= covered, sorted(files - covered)
