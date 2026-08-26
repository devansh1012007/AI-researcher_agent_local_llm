"""Outcome records, fingerprints, gain v2, quality dimensions (§6/§7/§32-35)."""
from __future__ import annotations

from tests.adaptive.helpers import _cfg, _run_deep_research, _store


def test_outcome_recorded_with_fingerprint_and_gain(tmp_path):
    from research_engine.services.context import ServiceContext
    cfg = _cfg(tmp_path)
    ctx = ServiceContext(cfg=cfg, data_dir=str(tmp_path))
    pid, res = _run_deep_research(
        cfg, ctx, "What is known about solid-state battery degradation?", "academic")
    outs = ctx.platform_db.list_outcomes(pid)
    assert len(outs) == 1
    o = outs[0]["data"]
    assert o["fingerprint"] and len(o["fingerprint"]) == 16
    assert o["research_type"] == "academic"
    assert {"queries_executed", "quality_metrics", "resource_metrics",
            "research_gain", "features"} <= set(o)
    # same objective+features ⇒ same fingerprint (§7 comparability)
    from research_engine.adaptive.outcomes import research_fingerprint
    fp = research_fingerprint(o["question"], "academic", o["features"],
                              o["policy_versions"], {"platform": "gar"})
    assert fp == o["fingerprint"]


def test_gain_v2_importance_weighting_not_gamed(tmp_path):
    """100 trivial claims must not beat 5 important verified ones (§34)."""
    from unittest.mock import MagicMock

    class FakeEv:
        def __init__(self, tier):
            self.source_tier = tier
            self.status = type("S", (), {"value": "EXTRACTED"})()
            self.retrieved_at = "9999-01-01T00:00:00+00:00"

    class FakeGap:
        def __init__(self, resolved, importance, qids):
            self.resolved = resolved
            self.importance = importance
            self.resolved_by_query_ids = qids

    orch = MagicMock()
    orch.repos.evidence.all.return_value = [FakeEv(5)] * 100   # trivial tier-5s
    orch.repos.gaps.all.return_value = []
    orch.repos.contradictions.all.return_value = []
    orch.repos.claims.all.return_value = []
    from research_engine.adaptive.outcomes import compute_gain_v2
    shallow = compute_gain_v2(orch, "p", "0000")["research_gain_v2"]

    orch.repos.evidence.all.return_value = [FakeEv(1)] * 5     # primary sources
    orch.repos.gaps.all.return_value = [
        FakeGap(True, 0.9, ["q1"]), FakeGap(True, 0.8, ["q2"]),
        FakeGap(False, 0.9, []), FakeGap(True, 0.3, ["q3"]),  # low-importance: no credit
        FakeGap(True, 0.7, []),                               # NO lineage: no credit (§35)
    ]
    deep = compute_gain_v2(orch, "p", "0000")["research_gain_v2"]
    assert deep > shallow, (deep, shallow)


def test_gap_rename_earns_nothing(tmp_path):
    """Cosmetic resolution without lineage earns zero gap credit (§35)."""
    from unittest.mock import MagicMock

    class FakeGap:
        resolved = True
        importance = 0.95
        resolved_by_query_ids: list = []

    orch = MagicMock()
    orch.repos.evidence.all.return_value = []
    orch.repos.gaps.all.return_value = [FakeGap()]
    orch.repos.contradictions.all.return_value = []
    orch.repos.claims.all.return_value = []
    from research_engine.adaptive.outcomes import compute_gain_v2
    g = compute_gain_v2(orch, "p", "0000")
    assert g["gaps_resolved_important"] == 0
    assert g["gaps_cosmetic_unlinked"] == 1


def test_quality_dimensions_multidimensional(tmp_path):
    from unittest.mock import MagicMock
    from research_engine.adaptive.outcomes import quality_dimensions

    def ev(i, tier):
        e = MagicMock()
        e.source_tier = tier
        e.status = type("S", (), {"value": "EXTRACTED"})()
        e.source_url = f"d{i}.example.com/x" if i % 2 else ""
        e.claim_text = "x"
        return e

    orch = MagicMock()
    orch.repos.claims.all.return_value = []
    orch.repos.evidence.all.return_value = [ev(i, 1) for i in range(4)]
    orch.repos.gaps.all.return_value = []
    orch.repos.contradictions.all.return_value = []
    s = MagicMock()
    s.content_status = "PARSED"
    s.domain = "d.example.com"
    s.source_tier = 1
    s.source_type = type("ST", (), {"value": "paper"})()
    orch.repos.sources.all.return_value = [s]
    dims = quality_dimensions(orch, "p")
    for k in ("claim_grounded_ratio", "avg_source_tier", "gap_coverage",
              "contradiction_integrity", "source_fetch_success",
              "source_domain_diversity"):
        assert k in dims
    assert dims["source_fetch_success"] == 1.0


def test_task_features_deterministic_buckets(tmp_path):
    from research_engine.adaptive.features import domain_bucket, extract_task_features
    assert domain_bucket("HIPAA compliant healthcare patient app") == \
        "regulated_industry"
    assert domain_bucket("transformer algorithm benchmark accuracy") == \
        "technical_science"
    f1 = extract_task_features("B2B SaaS pricing willingness to pay market", "startup")
    f2 = extract_task_features("B2B SaaS pricing willingness to pay market", "startup")
    assert f1 == f2                      # deterministic
    assert f1["market_orientation"] > 0 and f1["cross_domain"] is False \
        or f1["cross_domain"] is True    # shape sanity, no crash
