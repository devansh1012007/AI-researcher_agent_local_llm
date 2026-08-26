"""Quality dashboard, model policy, critic, budget, stopping (§24-§50, §86)."""
from __future__ import annotations

import pytest

from tests.adaptive.helpers import _cfg, _run_deep_research, _store


def test_dashboard_aggregates_everything(tmp_path):
    from research_engine.services.context import ServiceContext
    cfg = _cfg(tmp_path)
    ctx = ServiceContext(cfg=cfg, data_dir=str(tmp_path))
    pid, _ = _run_deep_research(cfg, ctx, "solid-state battery reliability", "academic")
    from research_engine.services.quality_service import QualityService
    d = QualityService(ctx).dashboard(pid)
    assert d["outcomes_summary"]["runs"] == 1
    assert isinstance(d["models"], list) and d["models"], \
        "llm telemetry must reach the dashboard"
    assert any(m["calls"] > 0 for m in d["models"])
    assert "diversity" in d and "policy_drift" in d


def test_model_degradation_detection_conservative(tmp_path):
    from research_engine.adaptive.model_policy import assess_models, detect_degradation
    db = _store(tmp_path)
    for _ in range(12):
        db.record_llm_call("ollama", "m1", "extractor", ok=True, latency_s=0.4)
        db.record_llm_call("ollama", "bad", "reasoning", ok=False, latency_s=9.9,
                           schema_failures=1)
    rows = assess_models(db, role="reasoning")
    bad = next(r for r in rows if r["model"] == "bad")
    assert bad["verdict"] == "degraded"
    assert bad["recommendation"] in ("fallback", "hold_and_investigate_schema")
    all_rows = assess_models(db)
    good = next(r for r in all_rows
                if r["model"] == "m1" and r["role"] == "extractor")
    assert good["verdict"] in ("healthy", "insufficient_data")
    assert detect_degradation(db, "reasoning") is not None
    assert detect_degradation(db, "synthesis") is None


def test_dynamic_budget_bounded_and_neutral_when_disabled(tmp_path):
    from research_engine.adaptive.budget import (
        gain_trend, scale_iteration_budget)
    base = 8
    # disabled ⇒ untouched (golden safety)
    for gains in ([0.0, 5.0], [5.0, 0.0], []):
        assert scale_iteration_budget(base, gains) == base
    improving = scale_iteration_budget(base, [1.0, 2.0, 3.0],
                                       policy_enabled=True, hard_cap=base)
    assert improving <= base                      # never exceeds hard cap
    diminishing = scale_iteration_budget(base, [3.0, 1.0, 0.5],
                                         policy_enabled=True)
    assert diminishing < base                     # taper on falling returns
    boosted = scale_iteration_budget(base, [1.0, 2.0, 4.0],
                                     policy_enabled=True, targeted_boost=2,
                                     hard_cap=99)
    assert base < boosted <= int(base * 1.25) + 2 + 1
    assert gain_trend([1.0]) == 0.0               # insufficient window


def test_stopping_policy_names_next_action(tmp_path):
    """Search-to-experiment transition (§49/§50)."""
    from unittest.mock import MagicMock
    from research_engine.adaptive.stopping import ResearchAction, recommend_next_action

    def gap(desc, imp=0.8):
        g = MagicMock()
        g.description = desc
        g.evidence_needed = ""
        g.importance = imp
        g.resolved = False
        return g

    orch = MagicMock()
    # experiment-resolvable uncertainty dominates: no contradictions, no
    # weak-sourced claims (those gate first — cheap verification before
    # expensive experiments), just the customer-behavior gap.
    orch.repos.gaps.all.return_value = [
        gap("do target customers actually pay? willingness to pay unknown"),
        gap("secondary detail", imp=0.2)]
    orch.repos.contradictions.all.return_value = []
    c = MagicMock()
    c.supported_by = ["ev_strong"]
    e = MagicMock()
    e.source_tier = 1
    orch.repos.claims.all.return_value = [c]
    orch.repos.evidence.get.return_value = e
    rec = recommend_next_action(orch, "p")
    assert rec["action"] == ResearchAction.DESIGN_EXPERIMENT.value
    assert "experiment" in rec["rationale"].lower()

    # weak-source claims gate BEFORE experiments (cheap primary fetch first)
    e.source_tier = 5
    rec2 = recommend_next_action(orch, "p")
    assert rec2["action"] == ResearchAction.FETCH_PRIMARY_SOURCE.value

    orch.repos.gaps.all.return_value = []
    orch.repos.contradictions.all.return_value = [MagicMock(resolved=False)]
    assert recommend_next_action(orch, "p")["action"] == \
        ResearchAction.SEARCH_COUNTEREVIDENCE.value

    orch.repos.contradictions.all.return_value = []
    orch.repos.claims.all.return_value = []
    assert recommend_next_action(orch, "p")["action"] == ResearchAction.STOP.value


def test_critic_finds_injected_defects_and_drops_hallucinated_targets(tmp_path):
    """§69: known-defect recall; LLM phantom ids dropped."""
    from unittest.mock import MagicMock
    from research_engine.adaptive.critic import critique_run

    class Claim:
        def __init__(self, cid, sup, kind="FACT", contra=None):
            self.id = cid
            self.supported_by = sup
            self.kind = type("K", (), {"value": kind})()
            self.contradicted_by = contra or []

    class Ev:
        def __init__(self, eid, tier=1):
            self.id = eid
            self.source_tier = tier
            self.status = type("S", (), {"value": "EXTRACTED"})()
            self.source_url = "a.example.com/1"
            self.claim_text = "x"
            self.numbers = []

    orch = MagicMock()
    claims = [
        Claim("clm_ok", ["ev_1"]),
        Claim("clm_dangling", ["ev_missing"]),          # injected defect 1
        Claim("clm_unsup", [], kind="FACT"),            # injected defect 2
    ]
    orch.repos.claims.all.return_value = claims
    orch.repos.evidence.all.return_value = [Ev("ev_1")]
    orch.repos.evidence.get.side_effect = (
        lambda eid: {"ev_1": Ev("ev_1")}.get(eid))
    orch.repos.gaps.all.return_value = []
    orch.repos.contradictions.all.return_value = []
    orch.repos.chunks.get.return_value = None
    orch.repos.sources.all.return_value = []
    rev = critique_run(orch, "p", level="STANDARD")
    kinds = {f["kind"] for f in rev["findings"]}
    assert "missing_cited_evidence" in kinds
    assert "unsupported_fact_claim" in kinds

    # HIGH_RIGOR with an LLM whose findings cite phantom ids → dropped+counted
    class FakeLLM:
        def structured(self, system, user, schema, max_attempts=3):
            out = schema.model_validate({
                "findings": [
                    {"kind": "factual_error", "severity": "high",
                     "target_id": "clm_dangling", "note": "real-ish"},
                    {"kind": "bias", "severity": "high",
                     "target_id": "ev_phantom", "note": "hallucinated"}]})
            return out, []

    rev2 = critique_run(orch, "p", run_id="r", level="HIGH_RIGOR",
                        llm=FakeLLM())
    llm_findings = [f for f in rev2["findings"]
                    if str(f["kind"]).startswith("llm_")]
    assert all(f["target_id"] != "ev_phantom" for f in llm_findings)
    dropped = [f for f in rev2["findings"]
               if f["kind"] == "llm_findings_dropped"]
    assert dropped and dropped[0]["note"].startswith("1 LLM findings")
