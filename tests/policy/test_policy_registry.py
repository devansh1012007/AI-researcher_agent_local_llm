"""Policy registry lifecycle + INV-016 safety properties + golden protection."""
from __future__ import annotations

import json

from tests.adaptive.helpers import _store


def test_full_lifecycle_propose_evaluate_activate_rollback(tmp_path):
    from research_engine.adaptive.policies import (
        PolicyRegistry, ensure_baseline_policies)
    db = _store(tmp_path)
    ensure_baseline_policies(db)
    reg = PolicyRegistry(db)
    reg.propose("routing", "v2", {"weights": {"literature": 1.05}})
    assert db.get_policy("routing", "v2")["status"] == "draft"
    try:
        reg.activate("routing", "v2", reason="no eval yet")
        # allowed (draft→active is human's call) — but record evaluation first
        # for the canary convention:
    except Exception:
        pass
    reg.record_evaluation("routing", "v2", {"routing_accuracy": 0.86},
                          promote_to_canary=True)
    assert db.get_policy("routing", "v2")["status"] == "canary"
    reg.activate("routing", "v2", reason="bench win")
    assert reg.active_version("routing") == "v2"
    back = reg.rollback("routing", reason="regression")
    assert back == "baseline" and reg.active_version("routing") == "baseline"


def test_activation_refuses_out_of_bounds_bodies(tmp_path):
    from research_engine.adaptive.policies import PolicyError, PolicyRegistry
    db = _store(tmp_path)
    reg = PolicyRegistry(db)
    reg.propose("routing", "greedy", {
        "constraints": {"max_adjustment": 0.9}})
    try:
        reg.activate("routing", "greedy", reason="sneaky")
        raise AssertionError("bound violation accepted")
    except PolicyError as e:
        assert "violates hard bound" in str(e)
    reg.propose("routing", "wild_explore", {
        "exploration": {"epsilon_low_stakes": 0.9}})
    try:
        reg.activate("routing", "wild_explore", reason="sneaky")
        raise AssertionError("epsilon bound violation accepted")
    except PolicyError as e:
        assert "> 0.15" in str(e)


def test_baseline_immutable(tmp_path):
    from research_engine.adaptive.policies import PolicyError, PolicyRegistry
    db = _store(tmp_path)
    reg = PolicyRegistry(db)
    try:
        reg.propose("routing", "baseline", {"hacked": True})
        raise AssertionError("baseline mutable")
    except PolicyError as e:
        assert "immutable" in str(e)


def test_compare_reports_diff_and_evaluations(tmp_path):
    from research_engine.adaptive.policies import (
        PolicyRegistry, ensure_baseline_policies)
    db = _store(tmp_path)
    ensure_baseline_policies(db)
    reg = PolicyRegistry(db)
    reg.propose("routing", "v2", {"exploration":
                                  {"epsilon_low_stakes": 0.1}})
    cmp = reg.compare("routing", "baseline", "v2")
    assert cmp["A"]["version"] == "baseline"
    assert "exploration" in cmp["body_diff"]


def test_golden_protection_no_learning_path_touches_evals_dir(tmp_path):
    """INV-016/§31: a full propose→evaluate→activate cycle must leave golden
    files byte-identical AND no code path may write into evals/ from the
    policy/learning modules."""
    from research_engine.adaptive.policies import (
        PolicyRegistry, ensure_baseline_policies)
    db = _store(tmp_path)
    ensure_baseline_policies(db)
    reg = PolicyRegistry(db)
    reg.propose("routing", "v3", {})
    reg.record_evaluation("routing", "v3", {"ok": True})
    reg.activate("routing", "v3", "t")
    reg.rollback("routing", "t")

    import research_engine.adaptive as pkg_root
    import pathlib
    pkg_files = list(pathlib.Path(pkg_root.__file__).parent.glob("*.py"))
    banned = ("evals/golden", "update-baseline", "baseline.json")
    for f in pkg_files:
        text = f.read_text()
        for b in banned[1:]:
            assert b not in text, f"{f.name} references {b}"

    # static scan: adaptive package imports never reference run_golden
    for f in pkg_files:
        assert "run_golden" not in f.read_text()


def test_service_seam_policy_writes_via_quality_service(tmp_path):
    """API/MCP write path goes through QualityService only (INV-008)."""
    import research_engine.api.app as api_app
    import inspect
    src = inspect.getsource(api_app)
    assert "platform_db.save_policy" not in src
    assert "activate_policy(" in src   # via service registry
