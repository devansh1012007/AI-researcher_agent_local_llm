"""INVARIANT-006: convergence cannot be triggered by failures alone
(audit P0-04). Adversarial scenarios per stabilization spec §31."""
from __future__ import annotations

import pytest

from research_engine.core.budget import Budget
from research_engine.models.enums import StopReason
from research_engine.reasoning.convergence import ConvergenceAnalyzer


def _cfg(new_ev_threshold=0.10, dup_conv=0.7):
    from research_engine.core.config import AppConfig
    cfg = AppConfig.load()
    cfg.research.new_evidence_threshold = new_ev_threshold
    cfg.research.duplicate_rate_converged = dup_conv
    return cfg


def _project():
    from research_engine.models.project import ResearchProject
    return ResearchProject(id="proj_x", question_raw="q")


def _budget(exhausted: bool = False):
    from research_engine.core.budget import Budget
    cfg = _cfg()
    b = Budget(cfg, _project())
    if exhausted:
        b.usage.queries_used = 10 ** 9
        b.usage.documents_used = 10 ** 9
    return b


class TestFailureVsConvergence:
    def test_provider_outage_is_not_convergence(self):
        """Queries ran and fetches FAILED: PROVIDER_DEGRADED, never CONVERGED."""
        a = ConvergenceAnalyzer(_cfg(), provider=None)
        d = a.evaluate(_project(), _budget(), {
            "total_evidence": 12, "new_evidence": 0,
            "fetch_successes": 0, "fetch_failures": 5,
            "queries_executed": 6,
            "duplicate_rate": 0.0, "rejection_rate": 0.0,
            "high_importance_gaps": 2, "new_claims": 0, "domains": 3,
        })
        assert d.stop_reason == StopReason.PROVIDER_DEGRADED

    def test_cached_silence_is_not_degradation(self):
        """Queries ran, fetches succeeded (dupes skipped), nothing new:
        that is SATURATION-shaped silence -> may converge on rate, but is
        NEVER labeled provider-degraded."""
        a = ConvergenceAnalyzer(_cfg(), provider=None)
        d = a.evaluate(_project(), _budget(), {
            "total_evidence": 12, "new_evidence": 0,
            "fetch_successes": 4, "fetch_failures": 0,
            "queries_executed": 6,
            "duplicate_rate": 0.02, "rejection_rate": 0.0,
            "high_importance_gaps": 2, "new_claims": 1, "domains": 3,
        })
        assert d.stop_reason != StopReason.PROVIDER_DEGRADED

    def test_hallucination_storm_is_not_convergence(self):
        """>70% verification rejections: extraction pathology -> flagged
        degraded for diagnosis; must NOT read as converged research."""
        a = ConvergenceAnalyzer(_cfg(dup_conv=0.7), provider=None)
        d = a.evaluate(_project(), _budget(), {
            "total_evidence": 30, "new_evidence": 1,
            "fetch_successes": 8, "queries_executed": 5,
            "duplicate_rate": 0.05, "rejection_rate": 0.75,
            "high_importance_gaps": 1, "new_claims": 0, "domains": 4,
        })
        assert d.stop_reason == StopReason.PROVIDER_DEGRADED
        assert "rejection" in d.rationale.lower()

    def test_true_duplicates_can_converge(self):
        """Genuine saturation (same quotes recurring) MAY converge — that is
        what duplicate pressure means now."""
        a = ConvergenceAnalyzer(_cfg(dup_conv=0.7), provider=None)
        d = a.evaluate(_project(), _budget(), {
            "total_evidence": 20, "new_evidence": 0,
            "fetch_successes": 6, "queries_executed": 4,
            "duplicate_rate": 0.85, "rejection_rate": 0.02,
            "high_importance_gaps": 0, "new_claims": 0, "domains": 2,
        })
        assert d.stop_reason == StopReason.CONVERGED

    def test_real_progress_continues(self):
        a = ConvergenceAnalyzer(_cfg(), provider=None)
        d = a.evaluate(_project(), _budget(), {
            "total_evidence": 15, "new_evidence": 6,
            "fetch_successes": 5, "queries_executed": 4,
            "duplicate_rate": 0.05, "rejection_rate": 0.03,
            "high_importance_gaps": 2, "new_claims": 3, "domains": 5,
        })
        assert not d.should_stop

    def test_budget_exhaustion_keeps_distinct_reason(self):
        b = _budget(exhausted=True)
        a = ConvergenceAnalyzer(_cfg(), provider=None)
        d = a.evaluate(_project(), b, {
            "total_evidence": 12, "new_evidence": 0, "fetch_successes": 0,
            "queries_executed": 9, "duplicate_rate": 0.0,
            "rejection_rate": 0.0, "high_importance_gaps": 1,
            "new_claims": 0, "domains": 1})
        # budget fires first and stays honest about WHY
        assert d.stop_reason == StopReason.BUDGET_EXHAUSTED


class TestMetricSemantics:
    def test_duplicate_rate_measures_duplication_not_rejection(self):
        """The metric rename enforced at the storage layer: rejected rows
        feed rejection_rate; repeated accepted quotes feed duplicate_rate."""
        import tempfile, pathlib
        from research_engine.models.evidence import Evidence
        from research_engine.storage.database import Database
        from research_engine.storage.repositories import EvidenceRepo
        db = Database(pathlib.Path(tempfile.mkdtemp()) / "t.sqlite")
        repo = EvidenceRepo(db)

        def mk(quote, status, i):
            e = Evidence(project_id="p", claim_text=f"c{i}", quote=quote,
                         source_id="s", source_tier=3, status=status)
            e.ensure_id()
            return e
        good = "Grounded retrieval reduces hallucinations in LLM systems."
        rows = [mk(good, "EXTRACTED", 1),
                mk(good, "EXTRACTED", 2),          # true duplicate
                mk("Completely different claim about logistics costs.", "EXTRACTED", 3),
                mk("Hallucinated passage that fails verification.", "REJECTED", 4)]
        for e in rows:
            repo.save(e)
        assert repo.duplicate_ratio("p") == pytest.approx(1 / 3, abs=0.01)
        assert repo.rejected_ratio("p") == pytest.approx(1 / 4, abs=0.01)
