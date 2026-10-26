"""Phase 3 tests: methodology designer/critic, validation designer, results,
decision layer."""
import pytest

from research_engine.models.reasoning import (Assumption, Experiment,
                                              Hypothesis, Methodology)
from research_engine.reasoning.decision_layer import DecisionLayer
from research_engine.reasoning.methodology_designer import (MethodologyCritic,
                                                            MethodologyDesigner)
from research_engine.reasoning.result_ingestion import (ResultIngestor,
                                                        approve_experiment)
from research_engine.storage.database import Database
from research_engine.storage.reasoning_repos import ReasoningRepos
from research_engine.storage.repositories import Repositories


@pytest.fixture()
def env(tmp_path):
    db = Database(tmp_path / "t.sqlite")
    return Repositories(db), ReasoningRepos(db)


def _hypo(rr):
    h = Hypothesis(project_id="p", title="M causes failure",
                   statement="Mechanism M causes failure under condition Y",
                   type="MECHANISTIC", predictions=["removing M restores performance"],
                   falsification_conditions=["removing M changes nothing"])
    rr.hypotheses.save(h)
    return h


class TestMethodologyDesigner:
    def test_multiple_tiers_generated(self, env):
        repos, rr = env
        h = _hypo(rr)
        meths = MethodologyDesigner(repos, rr, provider=None).design("p", h)
        tiers = {m.tier for m in meths}
        assert {"cheap_fast", "balanced", "high_rigor"} <= tiers

    def test_variables_baselines_criteria_present(self, env):
        repos, rr = env
        h = _hypo(rr)
        m = MethodologyDesigner(repos, rr, provider=None).design("p", h)[1]
        assert m.independent_vars and m.dependent_vars and m.control_vars
        tier_names = {b.get("tier") for b in m.baselines}
        assert {"naive", "existing"} <= tier_names
        assert m.success_condition and m.failure_condition and m.inconclusive_condition
        assert "before running" in m.success_condition.lower() or \
               "predefined" in m.success_condition.lower() or \
               "pre-defined" in m.success_condition.lower()

    def test_ablation_plan_for_mechanistic(self, env):
        repos, rr = env
        h = _hypo(rr)
        m = MethodologyDesigner(repos, rr, provider=None).design("p", h)[0]
        assert any("ablation" in a.lower() for a in m.ablation_plan)

    def test_critic_catches_missing_criteria(self, env):
        repos, rr = env
        h = _hypo(rr)
        bad = Methodology(project_id="p", hypothesis_id=h.id, tier="cheap_fast")
        bad.ensure_id()
        report = MethodologyCritic().inspect("p", bad, h)
        types = {p["type"] for p in report["problems"]}
        assert "POST_HOC_RISK" in types or "VARIABLES_UNDEFINED" in types


class TestValidationDesigner:
    def test_wtp_gets_behavioral_test_not_survey(self, env):
        from research_engine.reasoning.validation_designer import ValidationDesigner
        repos, rr = env
        h = Hypothesis(project_id="p", title="WTP", statement="customers will pay $50/mo",
                       type="WILLINGNESS_TO_PAY", domain="startup",
                       falsification_conditions=["no spending signal -> fail"])
        rr.hypotheses.save(h)
        a = Assumption(project_id="p", statement="clinics will pay $50 per month",
                       kind="critical", category="willingness_to_pay", hypothesis_id=h.id)
        rr.assumptions.save(a)
        tests = ValidationDesigner(rr).design_for_hypothesis("p", h, [a])
        assert tests[0].test_type == "preorder"
        assert tests[0].evidence_strength_class == "payment"

    def test_sequencing_stages_ordered(self, env):
        from research_engine.models.opportunity import Opportunity
        from research_engine.reasoning.hypothesis_engine import HypothesisGenerator
        from research_engine.reasoning.validation_designer import ValidationDesigner
        repos, rr = env
        opp = Opportunity(project_id="p", customer_segment="clinics",
                          problem="scheduling pain", current_alternative="paper")
        opp.ensure_id()
        hyps = HypothesisGenerator(repos, rr, provider=None).generate_business_hypotheses(
            "p", opp)
        asm_by = {}
        for h in hyps:
            a = Assumption(project_id="p", statement=h.statement[:150], kind="critical",
                           hypothesis_id=h.id, category=h.type.lower())
            rr.assumptions.save(a)
            asm_by[h.id] = [a]
        seq = ValidationDesigner(rr).sequence("p", opp, hyps, asm_by)
        stage_names = [s["stage"] for s in seq]
        assert any("Stage 1" in s for s in stage_names)
        assert any("willingness-to-pay" in s for s in stage_names)
        # WTP gate must come after problem gate
        wtp_idx = next(i for i, s in enumerate(seq) if "Stage 2" in s["stage"])
        problem_idx = next(i for i, s in enumerate(seq) if "Stage 1" in s["stage"])
        assert problem_idx < wtp_idx

    def test_validation_critic_flags_weak_signals(self, env):
        from research_engine.reasoning.validation_designer import ValidationCritic
        repos, rr = env
        x = Experiment(project_id="p", hypothesis_id="h1", methodology_id="m1",
                       title="Survey: would you use this product?",
                       decision_note="survey asking would you use this; no sample plan")
        x.ensure_id()
        result = ValidationCritic().inspect(x)
        types = {p["type"] for p in result["problems"]}
        assert "WEAK_COMMITMENT_SIGNAL" in types


class TestResultIngestion:
    def _setup_experiment(self, env):
        repos, rr = env
        h = _hypo(rr)
        m = Methodology(project_id="p", hypothesis_id=h.id, tier="balanced",
                        success_condition="Success: task success improves over the strongest baseline across seeds",
                        failure_condition="Failure: no meaningful improvement over baselines")
        m.ensure_id()
        rr.methodologies.save(m)
        x = Experiment(project_id="p", hypothesis_id=h.id, methodology_id=m.id,
                       title="Ablation")
        x.ensure_id()
        rr.experiments.save(x)
        approve_experiment(rr, "p", x.id, approved=None)
        approve_experiment(rr, "p", x.id, approved=True)
        return h, x

    def test_approval_gate_enforced(self, env):
        repos, rr = env
        h = _hypo(rr)
        x = Experiment(project_id="p", hypothesis_id=h.id, methodology_id="m1")
        x.ensure_id()
        rr.experiments.save(x)
        approve_experiment(rr, "p", x.id, approved=None)
        got = rr.experiments.get(x.id)
        assert got.status == "READY_FOR_HUMAN_APPROVAL"
        assert not got.approved_by_user  # system never self-approves

    def test_result_updates_hypothesis_and_creates_evidence(self, env):
        repos, rr = env
        h, x = self._setup_experiment(env)
        res = ResultIngestor(repos, rr).ingest(
            "p", x.id,
            observations=["success improves over the strongest baseline on repeated seeds"],
            metrics={"success": 0.8})
        assert res["verdict"] == "supports"
        ev = repos.evidence.get(res["evidence_id"])
        assert ev.source_type.value == "experiment_result"
        assert ev.source_tier == 1
        h_after = rr.hypotheses.get(h.id)
        assert h_after.status == "SUPPORTED"
        assert res["evidence_id"] in h_after.supporting_evidence
        raw = rr.experiment_results.get(res["result_id"])
        assert raw.raw_notes is not None  # raw preserved alongside interpretation

    def test_inconclusive_when_no_match(self, env):
        repos, rr = env
        h, x = self._setup_experiment(env)
        res = ResultIngestor(repos, rr).ingest("p", x.id,
                                               observations=["something unrelated happened"])
        assert res["verdict"] == "inconclusive"


class TestDecisionLayer:
    def test_ready_for_test_routes_to_experiment(self, env):
        repos, rr = env
        h = _hypo(rr)
        h.status = "READY_FOR_TEST"
        rr.hypotheses.save(h)
        nx = DecisionLayer(repos, rr).recommend_next("p")
        actions = [a["action"] for a in nx["actions"]]
        assert "EXPERIMENT" in actions

    def test_awaiting_approval_surfaces_first(self, env):
        repos, rr = env
        h = _hypo(rr)
        x = Experiment(project_id="p", hypothesis_id=h.id, methodology_id="m1",
                       status="READY_FOR_HUMAN_APPROVAL", title="gated test")
        x.ensure_id()
        rr.experiments.save(x)
        nx = DecisionLayer(repos, rr).recommend_next("p")
        assert nx["actions"][0]["action"] == "AWAIT_HUMAN_APPROVAL"

    def test_readiness_low_without_evidence(self, env):
        repos, rr = env
        dr = DecisionLayer(repos, rr).decision_readiness("p")
        assert dr["level"] in ("LOW", "MEDIUM")  # honest about empty state
