"""Startup validation designer: business hypotheses -> prioritized, staged
validation experiments with quality-aware critics.

Guardrails (spec #65/#66/#102):
- "Would you use this?" is weak evidence; payment/behavior is strong
- evidence hierarchy is explicit, not a law
- staged sequencing: never build big plans before core assumptions are tested
- system designs tests; humans execute consequential ones (spec #4/#77)
"""
from __future__ import annotations

import logging

from research_engine.models.enums import VALIDATION_EVIDENCE_HIERARCHY
from research_engine.models.reasoning import Assumption, Experiment, Hypothesis
from research_engine.models.opportunity import Opportunity
from research_engine.storage.reasoning_repos import ReasoningRepos

log = logging.getLogger(__name__)


class ValidationTest:
    """In-memory spec for one validation experiment (persisted as Experiment)."""

    def __init__(self, **kw):
        self.hypothesis_id = kw.get("hypothesis_id", "")
        self.assumption_id = kw.get("assumption_id", "")
        self.title = kw.get("title", "")
        self.test_type = kw.get("test_type", "interview")  # interview|survey|observation|
        # prototype_test|landing_page|fake_door|preorder|pilot|usage_measurement|ab_test
        self.procedure: list[str] = kw.get("procedure", [])
        self.target_participants = kw.get("target_participants", "")
        self.sample_requirement = kw.get("sample_requirement", "")
        self.bias_risks: list[str] = kw.get("bias_risks", [])
        self.success_metric = kw.get("success_metric", "")
        self.failure_metric = kw.get("failure_metric", "")
        self.decision_rule = kw.get("decision_rule", "")
        self.cost_estimate = kw.get("cost_estimate", "")
        self.expected_learning = kw.get("expected_learning", "")
        self.evidence_strength_class = kw.get("evidence_strength_class", "interview_evidence")
        self.risk_level = kw.get("risk_level", "LOW_RISK")

    @property
    def evidence_weight(self) -> float:
        return VALIDATION_EVIDENCE_HIERARCHY.get(self.evidence_strength_class, 0.3)


# test-type selection by assumption category (spec #36: not always surveys)
_TEST_TYPE_BY_CATEGORY = {
    "customer_frequency": ("observation", "repeated_behavioral_usage"),
    "problem_severity": ("interview", "interview_evidence"),
    "willingness_to_pay": ("preorder", "payment"),
    "willingness_to_pay_soft": ("fake_door", "survey_intention"),
    "distribution": ("pilot", "prototype_usage"),
    "switching": ("prototype_test", "prototype_usage"),
    "retention": ("usage_measurement", "repeated_behavioral_usage"),
}


class ValidationDesigner:
    def __init__(self, rrepos: ReasoningRepos):
        self.rrepos = rrepos

    def design_for_hypothesis(self, project_id: str, h: Hypothesis,
                              assumptions: list[Assumption]) -> list[ValidationTest]:
        tests = []
        for a in assumptions:
            category = a.category or self._infer_category(a.statement)
            ttype, strength = _TEST_TYPE_BY_CATEGORY.get(
                category, ("interview", "interview_evidence"))
            if ttype == "preorder" and h.domain != "startup":
                ttype, strength = "landing_page", "survey_intention"
            t = ValidationTest(
                hypothesis_id=h.id, assumption_id=a.id,
                title=f"Validate[{category or 'assumption'}]: {a.statement[:70]}",
                test_type=ttype,
                procedure=self._procedure(ttype),
                target_participants=self._participants(category),
                sample_requirement=("n>=15 for directional signal; n>=30 before "
                                    "treating as reliable" if ttype in ("interview", "observation")
                                    else "define minimum viable sample before launch"),
                bias_risks=self._bias_risks(ttype),
                success_metric=self._success_metric(ttype, category),
                failure_metric=self._failure_metric(ttype),
                decision_rule=("continue if success metric met; modify if between; "
                               "abandon/split the assumption if failure metric met"),
                cost_estimate={"observation": "low", "interview": "low",
                               "fake_door": "very low", "landing_page": "very low",
                               "preorder": "medium", "pilot": "high",
                               "prototype_test": "medium",
                               "usage_measurement": "medium"}.get(ttype, "?"),
                expected_learning=f"Whether '{a.statement[:60]}' holds behaviorally",
                evidence_strength_class=strength,
                risk_level="MEDIUM_RISK" if ttype in ("pilot", "preorder") else "LOW_RISK",
            )
            tests.append(t)
        return tests

    def persist_tests(self, project_id: str, h: Hypothesis,
                      methodology_id: str, tests: list[ValidationTest]) -> list[Experiment]:
        experiments = []
        for i, t in enumerate(tests):
            x = Experiment(project_id=project_id, hypothesis_id=h.id,
                           methodology_id=methodology_id,
                           title=f"[{t.test_type}] {t.title}",
                           risk_level=t.risk_level,
                           status="DESIGNED")
            x.decision_note = (
                f"type={t.test_type}; participants={t.target_participants}; "
                f"success={t.success_metric[:80]}; fail={t.failure_metric[:60]}; "
                f"biases={';'.join(t.bias_risks)[:100]}; cost={t.cost_estimate}; "
                f"decision={t.decision_rule[:80]}")
            x.ensure_id()
            self.rrepos.experiments.save(x)
            experiments.append(x)
        return experiments

    # -- prioritization & sequencing -------------------------------------------
    @staticmethod
    def prioritize(assumptions: list[Assumption], tests: dict[str, ValidationTest]
                   ) -> list[tuple[Assumption, float]]:
        """High consequence + cheaply falsifiable first (spec #38)."""
        scored = [(a, a.priority) for a in assumptions if not a.depends_on]
        scored.sort(key=lambda t: -t[1])
        return scored

    def sequence(self, project_id: str, opportunity, hypotheses: list[Hypothesis],
                 assumptions_by_hyp: dict[str, list[Assumption]]) -> list[dict]:
        """Staged sequence: problem -> WTP -> distribution -> retention (spec #39)."""
        stages = [
            ("Stage 1 — problem/frequency validation", ["CUSTOMER", "MARKET"]),
            ("Stage 2 — willingness-to-pay validation", ["WILLINGNESS_TO_PAY"]),
            ("Stage 3 — distribution/economics", ["DISTRIBUTION"]),
            ("Stage 4 — retention/business model", ["BUSINESS_MODEL"]),
        ]
        plan = []
        hyp_by_type = {h.type: h for h in hypotheses}
        for stage_name, types in stages:
            items = []
            for htype in types:
                h = hyp_by_type.get(htype)
                if not h:
                    continue
                asm_list = assumptions_by_hyp.get(h.id, [])
                gate = {
                    "stage": stage_name, "hypothesis_id": h.id,
                    "assumptions": [a.statement[:80] for a in asm_list][:3],
                    "tests": [f"{a.category or 'assumption'}: cheapest behavioral test first"
                              for a in asm_list][:2],
                    "gate_rule": ("proceed to next stage only if ALL critical assumptions "
                                  "in this stage pass; on failure: stop / modify / pivot"),
                }
                items.append(gate)
            if items:
                plan.extend(items)
        return plan

    # -- helpers -----------------------------------------------------------------
    @staticmethod
    def _infer_category(statement: str) -> str:
        s = statement.lower()
        if any(k in s for k in ("pay", "price", "$", "spend", "budget")):
            return "willingness_to_pay"
        if any(k in s for k in ("channel", "reach", "acquire", "distribut")):
            return "distribution"
        if any(k in s for k in ("retention", "churn", "keep using", "stay")):
            return "retention"
        if any(k in s for k in ("frequen", "weekly", "daily", "often")):
            return "customer_frequency"
        return "problem_severity"

    @staticmethod
    def _procedure(ttype: str) -> list[str]:
        procs = {
            "observation": ["recruit 10-15 target users", "observe current workflow unmodified",
                            "log time/cost spent on the problem behavior"],
            "interview": ["recruit 15-20 target customers (not friends/family)",
                          "ask about LAST specific occurrence (past behavior, not hypothetical)",
                          "probe workarounds and spending"],
            "preorder": ["landing page with concrete offer + price",
                         "collect refundable deposits / signed LOIs",
                         "count committed payments, not clicks"],
            "fake_door": ["advertise the capability honestly-bounded",
                          "measure click-through to purchase intent",
                          "follow up to separate curiosity from commitment"],
            "prototype_test": ["give 10 users a working prototype for >=1 week",
                               "measure unprompted return usage, not satisfaction forms"],
            "pilot": ["run bounded pilot with 3-5 design partners",
                      "define success metrics up front", "invoice real money where possible"],
            "usage_measurement": ["instrument the product", "cohort retention over >=4 weeks"],
        }
        return procs.get(ttype, ["define procedure before launching"])

    @staticmethod
    def _participants(category: str) -> str:
        return {
            "customer_frequency": "current members of the exact target segment",
            "problem_severity": "customers who recently performed the painful workflow",
            "willingness_to_pay": "budget holders, NOT end users only",
            "distribution": "actual channel operators/partners",
        }.get(category, "verified target-segment members")

    @staticmethod
    def _bias_risks(ttype: str) -> list[str]:
        risks = {
            "interview": ["leading questions", "social politeness bias",
                          "hypothetical answers are not behavior"],
            "survey": ["selection bias", "stated intent overstates behavior"],
            "fake_door": ["curiosity clicks misread as demand",
                          "brand trust inflates conversion"],
            "preorder": ["small-sample enthusiasm", "refund friction may suppress signups"],
            "prototype_test": ["novelty effect inflating early usage"],
            "pilot": ["hand-holding masks true adoption"],
        }
        base = ["wrong target customer recruited"]
        return risks.get(ttype, []) + base

    @staticmethod
    def _success_metric(ttype: str, category: str) -> str:
        m = {
            "preorder": ">=X% of targeted visitors place a refundable deposit (set X before launch)",
            "observation": ">=40% of observed users lose measurable time/money to the problem weekly",
            "interview": ">=50% describe an UNPROMPTED recent specific occurrence + workaround spend",
            "prototype_test": ">=40% return unprompted within week 2",
        }
        if category == "willingness_to_pay" and ttype not in ("preorder",):
            m["fake_door"] = "click-to-commit rate exceeds pre-set floor AND follow-up confirms budget authority"
        return m.get(ttype, "define numeric threshold BEFORE running")

    @staticmethod
    def _failure_metric(ttype: str) -> str:
        return {
            "preorder": "<2% deposit conversion after qualified traffic",
            "interview": "<20% report recurring occurrences",
            "observation": "<15% show meaningful cost from the problem",
        }.get(ttype, "below the success threshold after adequate sample")


# ---------------------------------------------------------------------------
# Validation critic (spec #65)
# ---------------------------------------------------------------------------

_WEAK_SIGNALS = ["would you use", "do you like", "would this be helpful", "interesting"]


class ValidationCritic:
    def inspect(self, experiment: Experiment) -> dict:
        problems: list[dict] = []
        note = experiment.decision_note.lower()
        if any(w in note for w in _WEAK_SIGNALS):
            problems.append({"type": "WEAK_COMMITMENT_SIGNAL", "severity": "high",
                             "description": "Plan relies on opinion questions; behavioral/"
                                            "payment signals required (spec #102)."})
        if "survey" in note and "payment" not in note:
            problems.append({"type": "STATED_INTENT_ONLY", "severity": "medium",
                             "description": "Survey intention is weaker than behavioral evidence."})
        if "n>=" not in note and "sample" not in note:
            problems.append({"type": "SMALL_SAMPLE_UNPLANNED", "severity": "medium",
                             "description": "No minimum sample requirement stated."})
        if "before launch" not in note and "before running" not in note and \
           experiment.status == "DESIGNED":
            problems.append({"type": "CRITERIA_NOT_PRESET", "severity": "medium",
                             "description": "Success thresholds should be fixed before running."})
        verdict = ("needs_revision" if any(p["severity"] == "high" for p in problems)
                   else "acceptable_with_notes" if problems else "sound")
        return {"experiment_id": experiment.id, "problems": problems, "verdict": verdict}
