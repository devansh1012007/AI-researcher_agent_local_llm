from research_engine.core.budget import Budget
from research_engine.core.config import AppConfig
from research_engine.models.enums import StopReason
from research_engine.models.project import BudgetUsage, ResearchProject
from research_engine.reasoning.convergence import ConvergenceAnalyzer


def _project() -> ResearchProject:
    return ResearchProject(question_raw="q", budget=BudgetUsage())


class TestBudget:
    def _budget(self, **overrides) -> tuple[Budget, AppConfig]:
        cfg = AppConfig.load()
        for k, v in overrides.items():
            setattr(cfg.research, k, v)
        p = _project()
        return Budget(cfg, p), cfg, p

    def test_budget_counts_spend(self):
        b, _, _ = self._budget(max_documents=3)
        b.spend_document()
        b.spend_document()
        assert b.documents_left() == 1

    def test_document_exhaustion(self):
        b, _, _ = self._budget(max_documents=1)
        b.spend_document()
        assert b.exhausted() == "documents"

    def test_llm_exhaustion(self):
        b, _, _ = self._budget(max_llm_calls=2)
        b.spend_llm(2)
        assert b.exhausted() == "llm_calls"

    def test_not_exhausted_initially(self):
        b, _, _ = self._budget()
        assert b.exhausted() is None

    def test_snapshot_has_all_dimensions(self):
        b, _, _ = self._budget()
        snap = b.snapshot()
        for key in ("queries", "documents", "llm_calls", "iterations", "minutes_elapsed"):
            assert key in snap


def _stats(**kw):
    base = {"total_evidence": 50, "new_evidence": 0, "new_claims": 0,
            "duplicate_rate": 0.0, "high_importance_gaps": 0, "domains": 4,
            "iteration": 3, "objective": "o"}
    base.update(kw)
    return base


class TestConvergence:
    def _analyzer(self, max_iterations=5):
        cfg = AppConfig.load()
        cfg.research.max_iterations = max_iterations
        return ConvergenceAnalyzer(cfg, provider=None)

    def test_stops_when_new_evidence_dies(self):
        a = self._analyzer()
        d = a.evaluate(_project(), _budget(), _stats(new_evidence=2))
        assert d.should_stop and d.stop_reason == StopReason.CONVERGED

    def test_continues_with_fresh_evidence_and_gaps(self):
        a = self._analyzer()
        d = a.evaluate(_project(), _budget(), _stats(new_evidence=20, new_claims=10,
                                                     high_importance_gaps=2))
        assert not d.should_stop

    def test_max_iterations_hard_stop(self):
        p = _project()
        p.budget.iterations_used = 5
        a = self._analyzer(max_iterations=5)
        d = a.evaluate(p, _budget_for(p), _stats(new_evidence=40))
        assert d.should_stop and d.stop_reason == StopReason.MAX_ITERATIONS

    def test_duplicate_saturation(self):
        a = self._analyzer()
        d = a.evaluate(_project(), _budget(), _stats(duplicate_rate=0.9))
        assert d.should_stop and d.stop_reason == StopReason.CONVERGED

    def test_early_research_never_converges_on_rate_alone(self):
        # small evidence pool: rate threshold should not trigger
        a = self._analyzer()
        d = a.evaluate(_project(), _budget(), _stats(total_evidence=5, new_evidence=0))
        assert not d.should_stop or d.stop_reason != StopReason.CONVERGED


def _budget():
    cfg = AppConfig.load()
    return Budget(cfg, _project())


def _budget_for(p):
    from research_engine.core.config import AppConfig
    return Budget(AppConfig.load(), p)
