"""Validation planning: assumption-ranked tests, staged sequencing,
information-gain prioritization, interview guides with leading-question
detection.

This module WIRES the existing (previously production-dead) ValidationDesigner
into the startup pipeline, and adds:
- information-gain scoring: cheap+decisive first (spec #41)
- interview guide generation with automatic leading-question detection and
  rewrite suggestions (spec #42)
- pricing-evidence discipline: opinion < stated WTP < budget < expenditure
  < actual payment are never treated as equivalent (spec #43)
"""
from __future__ import annotations

import re

from research_engine.reasoning.validation_designer import (
    ValidationCritic, ValidationDesigner)
from research_engine.specialists.startup.policies import (
    CUSTOMER_BEHAVIOR_UNCERTAINTIES)
from research_engine.storage.reasoning_repos import ReasoningRepos

_LEADING_PATTERNS = [
    (re.compile(r"\bwouldn'?t\b", re.I), "rhetorical 'wouldn't it' framing"),
    (re.compile(r"\bdo you think (?:you )?(?:would|could|might)\b", re.I),
     "hypothetical opinion prompt"),
    (re.compile(r"\bwould you use\b", re.I), "classic intention question"),
    (re.compile(r"\bdon'?t you think\b", re.I), "embedded agreement pressure"),
    (re.compile(r"\bisn'?t (?:it|this) (?:true|obvious)\b", re.I), "leading confirmation"),
    (re.compile(r"\bhow (?:excited|interested) (?:are|would) you\b", re.I),
     "invites enthusiasm inflation"),
]

_GOOD_PATTERNS = [
    r"\bwalk me through\b", r"\bhow do you currently\b", r"\btell me about the last time\b",
    r"\bwhen did you last\b", r"\bwhat did you do\b", r"\bhow much (?:time|money) did\b",
    r"\bhow did you\b", r"\blast (?:month|week|time)\b", r"\bthe last time\b",
]


class InterviewGuideDesigner:
    """Customer interview designer (spec #42)."""

    SECTIONS = [
        ("screening", "verify the candidate belongs to the exact target segment "
                      "(role, workflow, company profile) — disqualify politely otherwise"),
        ("opening", "context-setting; ask about their role and typical week"),
        ("behavior", "past behavior only: the LAST specific occurrence of the problem"),
        ("workflow", "step-by-step current process; tools touched; handoffs"),
        ("spending", "current spend of time/money on workarounds (facts, not opinions)"),
        ("severity", "what happens when it fails; who notices; cost of failure"),
        ("decision", "who decides, who pays, approval path for a purchase this size"),
        ("closing", "'who else should I talk to?' + permission for follow-up"),
    ]

    def build(self, topic: str, segment: str) -> dict:
        questions = {
            "screening": [f"Does your team handle {topic}? How often?"],
            "opening": ["Tell me about your role and what a typical week looks like."],
            "behavior": [f"Think about the LAST time {topic} came up — walk me through "
                         "exactly what you did, step by step."],
            "workflow": ["Which tools or people do you rely on for that process?"],
            "spending": ["What did that process cost you in time last month? Any direct spend?"],
            "severity": ["What happens downstream when this goes wrong?"],
            "decision": ["If you wanted to change how this works, who signs off and "
                         "what budget would that come from?"],
            "closing": ["Who else lives inside this process that I should talk to?"],
        }
        return {"segment": segment, "topic": topic,
                "sections": [{"section": name, "guidance": g,
                              "questions": questions.get(name, [])}
                             for name, g in self.SECTIONS]}

    @staticmethod
    def audit_questions(questions: list[str]) -> dict:
        """Detect leading/hypothetical questions and propose rewrites."""
        findings = []
        for q in questions:
            problems = []
            for rx, why in _LEADING_PATTERNS:
                if rx.search(q):
                    problems.append({"type": "LEADING_QUESTION", "why": why})
            if not any(re.search(p, q, re.I) for p in _GOOD_PATTERNS) and not problems:
                problems.append({"type": "HYPOTHETICAL_RISK", "why":
                                 "question asks about the future instead of past behavior"})
            rewrite = ""
            if problems:
                m = re.search(r"\b(?:automatically|tool that|software that)\s+(.{5,60})",
                              q, re.I)
                focus = m.group(1).rstrip("? ") if m else "that task"
                rewrite = f"How do you currently handle {focus}?"
            findings.append({"question": q, "problems": problems, "suggested_rewrite": rewrite})
        verdict = ("needs_revision" if any(f["problems"] for f in findings)
                   else "sound")
        return {"findings": findings, "verdict": verdict}


class ValidationPlanner:
    """Ranks tests by information gain per unit cost and sequences stages."""

    def __init__(self, rrepos: ReasoningRepos, srepos=None):
        self.rrepos = rrepos
        self.designer = ValidationDesigner(rrepos)
        self.critic = ValidationCritic()
        self.srepos = srepos

    COST_RANK = {"very low": 1.0, "low": 0.8, "medium": 0.5, "high": 0.25}

    def design_and_persist(self, project_id: str, opportunity_id: str,
                           hypotheses_with_assumptions: list[tuple]) -> list[dict]:
        """For each (hypothesis, assumptions): design tests, persist as
        Experiments, rank by expected information gain / effort.
        IDEMPOTENT: hypotheses that already have designed tests are skipped,
        so pipeline re-runs never duplicate validation work."""
        existing_hyp_ids = {x.hypothesis_id for x in
                            self.rrepos.experiments.all(project_id)}
        designed = []
        for h, assumptions in hypotheses_with_assumptions:
            if h.id in existing_hyp_ids:
                continue
            tests = self.designer.design_for_hypothesis(project_id, h, assumptions)
            experiments = self.designer.persist_tests(project_id, h, "", tests)
            for t, x in zip(tests, experiments):
                gain = t.evidence_weight * max(
                    (a.priority for a in assumptions
                     if a.id == getattr(t, "assumption_id", "")), default=0.5)
                cost = self.COST_RANK.get(t.cost_estimate.lower(), 0.5)
                info_gain = round(gain * cost * 4, 3)   # cheap+decisive first
                x.decision_note = (f"{x.decision_note}; opp={opportunity_id}; "
                                   f"info_gain={info_gain}")
                self.rrepos.experiments.save(x)
                designed.append({
                    "experiment_id": x.id, "hypothesis_id": h.id,
                    "assumption_id": getattr(t, "assumption_id", ""),
                    "title": x.title, "test_type": t.test_type,
                    "cost": t.cost_estimate,
                    "evidence_strength_class": t.evidence_strength_class,
                    "evidence_weight": t.evidence_weight,
                    "expected_information_gain": info_gain,
                    "critic_verdict": self.critic.inspect(x)["verdict"],
                })
        designed.sort(key=lambda d: -d["expected_information_gain"])
        return designed

    def sequence(self, project_id: str, opportunity, hypotheses: list,
                 assumptions_by_hyp: dict) -> list[dict]:
        """Staged plan via existing designer + next-test pointer (spec #40)."""
        stages = self.designer.sequence(project_id, opportunity, hypotheses,
                                        assumptions_by_hyp)
        return stages

    def biggest_uncertainty(self, assumptions: list) -> str | None:
        """Return the top uncertainty CATEGORY if it is customer-behavioral —
        i.e. internet research cannot resolve it (spec #70)."""
        ranked = sorted(assumptions, key=lambda a: -a.priority)
        for a in ranked[:3]:
            cat = a.category or ""
            if cat in CUSTOMER_BEHAVIOR_UNCERTAINTIES:
                return cat
        return None


# pricing evidence discipline helper (spec #43)
PRICING_EVIDENCE_LADDER = [
    ("price_opinion", 0.1), ("wtp_statement", 0.3), ("budget_evidence", 0.55),
    ("existing_expenditure", 0.8), ("actual_payment", 1.0),
]


def classify_pricing_evidence(text: str) -> tuple[str, float]:
    t = text.lower()
    if re.search(r"\bpaid|invoice|transact\w+|deposit|subscri\w+\b", t):
        return PRICING_EVIDENCE_LADDER[4]
    if re.search(r"\bspends? \$?₹?€?£?\d|\bbudget (?:of|is)\b|\bcurrently pay\w*\b", t):
        return PRICING_EVIDENCE_LADDER[3]
    if re.search(r"\bbudget\w*\b|\ballocated\b", t):
        return PRICING_EVIDENCE_LADDER[2]
    if re.search(r"\bwould pay\b|\bwilling to pay\b|\bintend to buy\b", t):
        return PRICING_EVIDENCE_LADDER[1]
    if re.search(r"\b(?:seems?|looks?|feel\w+) (?:cheap|expensive|pricey)\b|\bopinion\b", t):
        return PRICING_EVIDENCE_LADDER[0]
    return ("unclassified", 0.2)
