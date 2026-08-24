"""Phase 3 acceptance tests (spec #109): hypotheses, methodology, startup,
research loop, grounding — fully offline."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

from research_engine.models.reasoning import Assumption, Hypothesis
from research_engine.core.config import AppConfig
from research_engine.reasoning.decision_layer import DecisionLayer
from research_engine.reasoning.hypothesis_engine import (HypothesisGenerator,
                                                         HypothesisLifecycle,
                                                         rank_hypotheses)
from research_engine.reasoning.methodology_designer import MethodologyDesigner
from research_engine.reasoning.pipeline import ReasoningPipeline
from research_engine.reasoning.result_ingestion import (ResultIngestor,
                                                        approve_experiment)
from research_engine.reasoning.validation_designer import ValidationDesigner
from research_engine.storage.reasoning_repos import ReasoningRepos


def _run(cfg, fake_registry, make_orchestrator, question, mode="academic"):
    orch = make_orchestrator(question, mode=mode)
    orch.repos.projects.save(orch.project)
    return orch, orch.run()


class TestHypothesisAcceptance:
    def test_full_pipeline_from_research(self, cfg, fake_registry, make_orchestrator):
        orch, p = _run(cfg, fake_registry, make_orchestrator,
                       "Why do LLM planners fail on long-horizon manipulation tasks?")
        pipe = ReasoningPipeline(orch.repos, ReasoningRepos(orch.db),
                                 orch.router.reasoning, fake_registry)
        summary = pipe.run_for_project(p.id, mode="academic")
        assert summary["generated"], "hypotheses must be generated from gaps"
        # multiple + competing
        assert len(summary["ranked"]) >= 2
        rr2 = ReasoningRepos(orch.repos.db)
        hyps = [rr2.hypotheses.get(r["id"]) for r in summary["ranked"]]
        hyps = [h for h in hyps if h]
        families = {}
        for h in hyps:
            families.setdefault(h.alternative_of, []).append(h)
        multi = [f for f, members in families.items() if f and len(members) >= 2]
        assert multi or len(families) >= 2, "competing sets must exist"
        # every hypothesis traceable to origin + falsifiable
        for h in hyps:
            assert h.origin_refs, "provenance required"
            assert h.falsification_conditions, "falsification required"

    def test_history_and_ranking(self, cfg, fake_registry, make_orchestrator):
        orch, p = _run(cfg, fake_registry, make_orchestrator,
                       "Ranking test question about planner benchmarks.")
        rr = ReasoningRepos(orch.db)
        pipe = ReasoningPipeline(orch.repos, rr, None, fake_registry)
        pipe.run_for_project(p.id)
        ranked = rank_hypotheses(orch.repos, rr, p.id)
        assert ranked
        top = ranked[0]["hypothesis"]
        lc = HypothesisLifecycle(rr)
        lc.revise(p.id, top, {"title": top.title + " (rev)"}, reason="test revision")
        history = rr.hypothesis_versions.history(p.id, top.id)
        assert history[-1].version == 2
        assert history[-1].snapshot["title"] == top.title.replace(" (rev)", "")


class TestMethodologyAcceptance:
    def test_design_compare_critique(self, tmp_path):
        from research_engine.storage.database import Database
        from research_engine.storage.repositories import Repositories
        db = Database(tmp_path / "t.sqlite")
        repos = Repositories(db)
        rr = ReasoningRepos(db)
        h = Hypothesis(project_id="p", title="T", statement="M causes Y",
                       type="CAUSAL", predictions=["intervention changes outcome"],
                       falsification_conditions=["no change -> fail"])
        rr.hypotheses.save(h)
        designer = MethodologyDesigner(repos, rr, provider=None)
        meths = designer.design("p", h)
        assert len(meths) >= 3
        rows = designer.compare("p", h.id)
        assert len(rows) == len(meths)
        assert all("success_criterion_defined" in r for r in rows)


class TestStartupValidationAcceptance:
    def test_business_chain_to_sequenced_tests(self, tmp_path):
        from research_engine.models.opportunity import Opportunity
        from research_engine.storage.database import Database
        from research_engine.storage.repositories import Repositories
        repos = Repositories(Database(tmp_path / "t.sqlite"))
        rr = ReasoningRepos(repos.db)
        opp = Opportunity(project_id="p", customer_segment="clinics",
                          problem="scheduling is manual", current_alternative="paper")
        opp.ensure_id()
        gen = HypothesisGenerator(repos, rr, provider=None)
        hyps = gen.generate_business_hypotheses("p", opp)
        asm_by = {}
        for h in hyps:
            a = Assumption(project_id="p", statement=h.statement[:150], kind="critical",
                           hypothesis_id=h.id, category=h.type.lower())
            rr.assumptions.save(a)
            a.depends_on = []
            asm_by[h.id] = [a]
        vd = ValidationDesigner(rr)
        seq = vd.sequence("p", opp, hyps, asm_by)
        assert len(seq) >= 3, "staged validation sequence required"
        # opportunity confidence updatable via result ingestion
        h_wtp = next(h for h in hyps if h.type == "WILLINGNESS_TO_PAY")
        x = vd.persist_tests("p", h_wtp, "meth", vd.design_for_hypothesis(
            "p", h_wtp, asm_by[h_wtp.id]))[0]
        approve_experiment(rr, "p", x.id, approved=None)
        approve_experiment(rr, "p", x.id, approved=True)
        res = ResultIngestor(repos, rr).ingest(
            "p", x.id,
            observations=["3 clinics placed refundable deposits after pricing page"],
            metrics={"deposits": 3})
        assert res["verdict"] in ("supports", "inconclusive")


class TestDecisionReadiness:
    def test_next_and_readiness(self, tmp_path):
        from research_engine.storage.database import Database
        from research_engine.storage.repositories import Repositories
        repos = Repositories(Database(tmp_path / "t.sqlite"))
        rr = ReasoningRepos(repos.db)
        dl = DecisionLayer(repos, rr)
        out = dl.recommend_next("p")
        assert "actions" in out and "headline" in out
        dr = dl.decision_readiness("p")
        assert dr["level"] in ("LOW", "MEDIUM", "HIGH")
        assert isinstance(dr["research_debt"], list)


# eval runner integration: phase3 task runs end-to-end offline
def test_phase3_eval_task_offline(tmp_path):
    from evals.metrics.eval_metrics import score_project
    from evals.runners.run_eval import load_tasks, run_offline
    tasks = load_tasks(ROOT / "evals/datasets/phase3_tasks.json")
    task = tasks[0]
    from research_engine.core.config import AppConfig
    cfg = AppConfig.load()
    cfg.storage.data_dir = str(tmp_path / task["id"])
    cfg.research.max_iterations = 1
    orch, _ = run_offline(task, cfg)
    s = score_project(orch.repos, orch.project.id)
    assert s.quote_correctness >= task["quality_expectations"]["min_quote_correctness"]
