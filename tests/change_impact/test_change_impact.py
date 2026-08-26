"""Change impact traversal + drift/diversity monitors (§71-§78, §81-§82)."""
from __future__ import annotations

from unittest.mock import MagicMock

from tests.adaptive.helpers import _store


def _chain_orch(pid="p"):
    orch = MagicMock()

    def ev(eid):
        e = MagicMock()
        e.id = eid
        e.status = type("S", (), {"value": "EXTRACTED"})()
        return e

    claim = MagicMock()
    claim.id = "clm_1"
    claim.supported_by = ["ev_new"]
    claim.contradicted_by = []
    hyp = MagicMock()
    hyp.id = "hyp_1"
    hyp.supporting_evidence = []
    hyp.contradicting_evidence = ["ev_new"]
    opp = MagicMock()
    opp.id = "opp_1"
    opp.evidence_ids = ["ev_new"]
    opp.market_signal_evidence_ids = []
    opp.severity = 0.3
    orch.repos.claims.all.return_value = [claim]
    orch.repos.hypotheses.all.return_value = [hyp]
    orch.repos.opportunities.all.return_value = [opp]
    return orch


def test_traversal_follows_persisted_links_downstream(tmp_path):
    from research_engine.adaptive.impact import analyze_new_evidence
    impact = analyze_new_evidence(_chain_orch(), "p", ["ev_new"])
    assert {"relation": "supported", "claim_id": "clm_1"} in impact["claims"]
    assert impact["hypotheses"][0]["relation"] == "contradicted"
    assert impact["opportunities"] == [
        {"opportunity_id": "opp_1", "weakened": True}]


def test_no_inference_from_unlinked_evidence(tmp_path):
    from research_engine.adaptive.impact import analyze_new_evidence
    impact = analyze_new_evidence(_chain_orch(), "p", ["ev_unrelated"])
    assert impact == {"claims": [], "hypotheses": [], "opportunities": []}


def test_raise_alerts_bounded_kinds_only(tmp_path):
    from research_engine.adaptive.impact import raise_impact_alerts
    db = _store(tmp_path)
    raised = raise_impact_alerts(db, _chain_orch(), "p", ["ev_new"],
                                 source="test")
    kinds = {r["kind"] for r in raised}
    assert kinds <= {"CLAIM_CONTRADICTION", "HYPOTHESIS_FALSIFIED",
                     "OPPORTUNITY_WEAKENED", "HIGH_IMPACT_NEW_EVIDENCE"}
    assert "HYPOTHESIS_FALSIFIED" in kinds


def test_diversity_flags_concentration_but_never_forces(tmp_path):
    from research_engine.adaptive.drift import diversity_report
    db = _store(tmp_path)
    for _ in range(10):
        db.record_specialist_perf("literature", "1.0", "academic",
                                  ok=True, latency_s=0.1)
        db.record_llm_call("mock", "only-model", "extractor", ok=True,
                           latency_s=0.1)
    rep = diversity_report(db)
    assert rep["specialists"]["concentration_flag"] is True   # diagnostic
    assert list(rep["specialists"]["shares"]) == ["literature"]
    assert rep["models"]["concentration_flag"] is True
    # monitors are read-only: nothing mutated
    assert len(db.list_specialist_perf()) == 1


def test_policy_drift_report_windows(tmp_path):
    from research_engine.adaptive.drift import policy_drift_report
    db = _store(tmp_path)
    for i in range(6):
        db.save_decision(f"d{i}", "p", "select_specialist",
                         "startup" if i < 4 else "foresight",
                         [], "t", "routing@baseline", {})
    rep = policy_drift_report(db)
    assert rep["status"] == "insufficient_data"      # <10 decisions
    for i in range(10):
        db.save_decision(f"e{i}", "p", "select_specialist",
                         "literature" if i >= 6 else "startup",
                         [], "t", "routing@baseline", {})
    rep = policy_drift_report(db)
    assert rep["status"] == "ok"
    assert isinstance(rep["significant_shifts"], dict)
