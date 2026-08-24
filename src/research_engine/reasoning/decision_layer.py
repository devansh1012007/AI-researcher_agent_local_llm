"""Decision layer: what should happen NEXT (spec #90/#91/#108).

Classifies the highest-leverage next action per uncertainty:
  more web/paper/primary-source research vs. user input vs. an experiment.
Also: decision readiness estimate with visible factors, and research debt.

Rule (spec #89/#90): do not search endlessly when real-world evidence is the
bottleneck — informational uncertainty -> research; empirical uncertainty -> test;
user-only knowledge -> ask.
"""
from __future__ import annotations

from dataclasses import dataclass

from research_engine.models.enums import EvidenceStatus
from research_engine.reasoning.priority import BranchCoverageModel
from research_engine.storage.reasoning_repos import ReasoningRepos
from research_engine.storage.repositories import Repositories


@dataclass
class NextAction:
    action: str            # WEB_SEARCH | PAPER_SEARCH | PRIMARY_SOURCE_SEARCH |
                           # DOCUMENT_REVIEW | USER_INPUT | INTERVIEW | SURVEY |
                           # PROTOTYPE | EXPERIMENT | SIMULATION | WAIT_FOR_DATA |
                           # HYPOTHESIS_REFINEMENT | METHODOLOGY_IMPROVEMENT | ABANDON
    target_id: str         # hypothesis/gap/claim the action serves
    question: str = ""
    reason: str = ""
    expected_information_gain: float = 0.5
    cost: str = "low"
    rationale: str = ""


EMPIRICAL_CATEGORIES = {"willingness_to_pay", "distribution", "retention",
                        "switching", "customer_frequency"}
USER_ONLY_CATEGORIES = {"budget_constraints", "geography_priority", "risk_tolerance"}


def classify_uncertainty(repos: Repositories, project_id: str,
                         gap) -> str:
    """Is this gap answerable from documents, only by users, or only empirically?"""
    text = (gap.description + " " + gap.evidence_needed).lower()
    if any(k in text for k in ("would they pay", "willingness", "will customers",
                               "in practice", "in the field", "real users")):
        return "empirical"
    if any(k in text for k in ("which segment matters most", "user preference",
                              "which geography", "constraint")):
        return "user_input"
    return "informational"


class DecisionLayer:
    def __init__(self, repos: Repositories, rrepos: ReasoningRepos):
        self.repos = repos
        self.rrepos = rrepos

    def recommend_next(self, project_id: str, objective: str = "balanced") -> dict:
        """'What should I do next?' engine (spec #108)."""
        actions: list[NextAction] = []

        # 1. hypotheses needing evidence -> targeted research or tests
        for h in self.rrepos.hypotheses.by_status(project_id, "NEEDS_EVIDENCE",
                                                  "PROPOSED", "REFINED",
                                                  "READY_FOR_TEST"):
            missing = not h.supporting_evidence
            empirical_assumptions = [
                a for a in self.rrepos.assumptions.for_hypothesis(project_id, h.id)
                if a.category in EMPIRICAL_CATEGORIES or
                any(k in a.statement.lower() for k in ("pay", "buy", "use it weekly"))]
            if h.status == "READY_FOR_TEST":
                actions.append(NextAction(
                    action="EXPERIMENT", target_id=h.id, question=h.statement[:120],
                    reason="hypothesis is READY_FOR_TEST; remaining uncertainty is "
                           "empirical, not informational (spec #89)",
                    expected_information_gain=0.9, cost="medium"))
            elif empirical_assumptions:
                a = max(empirical_assumptions, key=lambda x: x.priority)
                actions.append(NextAction(
                    action="INTERVIEW" if "interview" in (a.falsification_test or "").lower()
                           else "EXPERIMENT",
                    target_id=h.id, question=a.statement[:120],
                    reason=f"assumption '{a.statement[:60]}' is testable cheaply now; "
                           "further searching would not resolve behavioral unknowns",
                    expected_information_gain=0.85, cost="low-medium"))
            elif missing:
                actions.append(NextAction(
                    action="PAPER_SEARCH" if h.domain == "scientific" else "PRIMARY_SOURCE_SEARCH",
                    target_id=h.id, question=h.statement[:120],
                    reason="no supporting evidence yet; informational gap remains",
                    expected_information_gain=0.7))

        # 2. open gaps via existing coverage model
        plans = self.repos.plans.all(project_id)
        if plans:
            coverage = BranchCoverageModel(self.repos).compute(project_id, plans[-1].branches)
            for cov in coverage.values():
                if cov["unanswered"] and cov["importance"] >= 0.6:
                    actions.append(NextAction(
                        action="WEB_SEARCH", target_id=cov["branch_id"],
                        question=cov["question"][:120],
                        reason=f"important branch uncovered (coverage {cov['coverage']:.2f})",
                        expected_information_gain=0.75))
                elif cov["weakly_answered"] and cov["importance"] >= 0.65:
                    actions.append(NextAction(
                        action="PRIMARY_SOURCE_SEARCH", target_id=cov["branch_id"],
                        question=cov["question"][:120],
                        reason="covered only by low-tier sources",
                        expected_information_gain=0.6))

        # 3. experiments awaiting human approval always surface first (spec #77)
        pending = self.rrepos.experiments.awaiting_approval(project_id)
        for x in pending:
            actions.insert(0, NextAction(
                action="AWAIT_HUMAN_APPROVAL", target_id=x.id,
                question=x.title[:120],
                reason="experiment designed and gated on human approval",
                expected_information_gain=1.0, cost="zero"))

        actions.sort(key=lambda a: -a.expected_information_gain)
        return {
            "objective": objective,
            "actions": [a.__dict__ for a in actions[:8]],
            "headline": (actions[0].reason if actions else
                         "no high-value actions identified; consider synthesis"),
        }

    def decision_readiness(self, project_id: str) -> dict:
        """LOW/MEDIUM/HIGH readiness with visible factors (spec #88)."""
        factors = {}
        n_ev = self.repos.evidence.count(project_id, "status!='REJECTED'")
        factors["evidence_volume"] = min(1.0, n_ev / 25)
        claims = self.repos.claims.all(project_id)
        supported = [c for c in claims if c.supported_by]
        factors["claim_support_ratio"] = (len(supported) / len(claims)) if claims else 0.0
        crit = self.rrepos.assumptions.all(project_id, "kind='critical'")
        validated = [a for a in crit if a.status == "validated"]
        factors["critical_assumptions_validated"] = (
            len(validated) / len(crit)) if crit else 0.5
        unresolved_con = self.rrepos.hypotheses.count(project_id, "status='CONTRADICTED'")
        falsified = self.rrepos.hypotheses.count(project_id, "status='FALSIFIED'")
        factors["contradiction_load"] = max(0.0, 1.0 - 0.2 * (unresolved_con + falsified))
        gaps_open = self.repos.gaps.count(project_id, "resolved=0 AND importance>=0.6")
        factors["high_importance_gaps_clear"] = max(0.0, 1.0 - 0.25 * gaps_open)

        score = (0.25 * factors["evidence_volume"]
                 + 0.2 * factors["claim_support_ratio"]
                 + 0.25 * factors["critical_assumptions_validated"]
                 + 0.15 * factors["contradiction_load"]
                 + 0.15 * factors["high_importance_gaps_clear"])
        level = "HIGH" if score >= 0.7 else "MEDIUM" if score >= 0.45 else "LOW"
        debt = self._research_debt(project_id)
        return {"level": level, "score": round(score, 3), "factors": factors,
                "research_debt": debt}

    def _research_debt(self, project_id: str) -> list[str]:
        """Important unresolved items before decisions can be trusted (spec #87)."""
        debt = []
        unverified_crit = [a for a in self.rrepos.assumptions.all(
            project_id, "kind='critical' AND status='unverified'", ())]
        for a in unverified_crit[:5]:
            debt.append(f"critical assumption unvalidated: {a.statement[:80]}")
        weak_claims = [c for c in self.repos.claims.all(project_id)
                       if c.confidence >= 0.55 and len(c.supported_by) < 2]
        for c in weak_claims[:3]:
            debt.append(f"influential claim rests on a single source: {c.text[:70]}")
        return debt
