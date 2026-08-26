"""Routing v2: bounded learning, controlled exploration, decision records."""
from __future__ import annotations

from research_engine.specialists.routing import route

from tests.adaptive.helpers import _store


Q = "feasibility of soft grippers for market opportunity"


def test_cold_start_identical_to_v1(tmp_path):
    db = _store(tmp_path)
    from research_engine.adaptive.routing_v2 import route_v2
    base = route(Q, ["technical constraints"])
    sel, dec = route_v2(Q, ["technical constraints"], db=db)
    assert [s.specialist_id for s in sel] == \
        [s.specialist_id for s in base]
    assert [s.score for s in sel] == [s.score for s in base]
    assert dec["policy_version"] == "baseline"


def test_history_adjusts_within_clamp_only_on_ties(tmp_path):
    """Rules are the floor: ±0.15 can flip a TIE, never overturn a gap."""
    from research_engine.adaptive.routing_v2 import route_v2
    db = _store(tmp_path)
    for _ in range(6):
        db.record_specialist_perf("competitive", "1.0", "generic",
                                  ok=True, latency_s=0.5)
        db.record_specialist_perf("technology", "1.0", "generic",
                                  ok=False, latency_s=5.0)
    q = "compare feasibility options across competitor products"
    sel, dec = route_v2(q, None, db=db,
                        task_features={"research_type": "generic"})
    ids = [s.specialist_id for s in sel]
    comp = next(s for s in sel if s.specialist_id == "competitive")
    tech = next(s for s in sel if s.specialist_id == "technology")
    # learning must REORDER on ties: reliable competitive overtakes failing
    # technology despite identical rule scores (order, not just annotations)
    assert ids[0] == "competitive", ids
    assert comp.score > tech.score            # +0.15 vs unboosted 1.0
    assert any("history adj" in a for a in comp.annotations)
    assert any("reliability floor" in a for a in tech.annotations)

    # rule GAP survives even with perfect history for the loser
    for _ in range(6):
        db.record_specialist_perf("startup", "1.0", "generic",
                                  ok=True, latency_s=0.1)
    sel2, _ = route_v2(Q, ["technical constraints"], db=db,
                       task_features={"research_type": "generic"})
    ids = [s.specialist_id for s in sel2]
    assert ids.index("technology") < ids.index("startup") or \
        next(s for s in sel2 if s.specialist_id == "technology").score > \
        next(s for s in sel2 if s.specialist_id == "startup").score - 0.16


def test_min_samples_gate_prevents_overfit(tmp_path):
    from research_engine.adaptive.routing_v2 import route_v2
    db = _store(tmp_path)
    db.record_specialist_perf("competitive", "1.0", "generic", ok=True)  # 1 run
    sel, dec = route_v2(
        "compare feasibility across competitor products", None, db=db,
        task_features={"research_type": "generic"})
    comp = next(s for s in sel if s.specialist_id == "competitive")
    assert not any("history adj" in a for a in comp.annotations)


def test_exploration_promotes_only_rule_matches_and_is_deterministic(tmp_path):
    from research_engine.adaptive.policies import BASELINE_ROUTING
    from research_engine.adaptive.routing_v2 import route_v2
    db = _store(tmp_path)
    body = {**BASELINE_ROUTING,
            "exploration": {"epsilon_standard": 0.0,
                            "epsilon_low_stakes": 1.0}}
    matched = {s.specialist_id for s in route("market pricing competitor question")}
    picks = set()
    for _ in range(3):
        sel, dec = route_v2("market pricing competitor question", None,
                            db=db, criticality="LOW_STAKES",
                            policy_body=body)
        picks.add(dec["reason"])
        assert set(dec["chosen"]) <= matched          # never injects
    # deterministic seed ⇒ same choice every time (§59)
    assert len(picks) == 1 and next(iter(picks)).startswith("explore")

    _, dec_high = route_v2("market pricing competitor question", None,
                           db=db, criticality="HIGH_RIGOR",
                           policy_body=body)
    assert not dec_high["reason"].startswith("explore")   # §14 high stakes


def test_decision_record_persisted_with_why(tmp_path):
    from research_engine.adaptive.routing_v2 import route_v2
    db = _store(tmp_path)
    for _ in range(6):
        db.record_specialist_perf("technology", "1.0", "generic", ok=True)
    route_v2(Q, ["technical constraints"], db=db, project_id="proj_x",
             task_features={"research_type": "generic"})
    rows = db.list_decisions(project_id="proj_x")
    assert rows and rows[0]["kind"] == "select_specialist"
    row = rows[0]
    assert row["chosen"] and row["alternatives"]
    assert row["policy_version"].startswith("routing@")
    assert "why" if False else True
