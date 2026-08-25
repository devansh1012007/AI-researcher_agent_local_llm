"""Business assumption engine.

Fixes a structural gap: business hypotheses previously never received real
`Assumption` entities, leaving the validation designer with nothing to work
from. Here every business hypothesis gets assumptions as first-class rows in
the reasoning store (assumptions2), ranked by the standard priority formula
(importance × uncertainty × impact_of_failure × testability — spec #37).
"""
from __future__ import annotations

import re

from research_engine.models.reasoning import Assumption
from research_engine.providers.llm.base import LLMProvider
from research_engine.storage.reasoning_repos import ReasoningRepos

_CATEGORY_HINTS = [
    ("willingness_to_pay", re.compile(r"\b(pay|price|spend|budget|willing)\b", re.I)),
    ("distribution", re.compile(r"\b(reach|channel|acquire|distribut)\b", re.I)),
    ("retention", re.compile(r"\b(retain|churn|stay|keep using|renew)\b", re.I)),
    ("customer_frequency", re.compile(r"\b(frequen|daily|weekly|often|repeat)\b", re.I)),
    ("switching", re.compile(r"\b(switch|migrate|leave current|replace)\b", re.I)),
    ("problem_severity", re.compile(r"\b(severe|painful|urgent|important enough)\b", re.I)),
    ("technology_feasibility", re.compile(r"\b(technic\w+|feasib\w+|possible to build|accurate enough)\b", re.I)),
    ("regulation_permits", re.compile(r"\b(regulat\w+|legal|compliance|licens\w+)\b", re.I)),
]

# Universal viability assumptions (deterministic fallback, spec #36)
_FALLBACK_ASSUMPTIONS = [
    "customers experience the problem frequently enough to act on it",
    "customers care enough about the problem to solve it",
    "customers can pay for a solution",
    "existing alternatives are inadequate for the core need",
    "the segment can be reached economically",
    "retention is possible once adopted",
    "technology can solve the problem at acceptable quality",
    "regulation permits the proposed solution",
]


def infer_category(statement: str) -> str:
    for name, rx in _CATEGORY_HINTS:
        if rx.search(statement):
            return name
    return "problem_severity"


class BusinessAssumptionBuilder:
    def __init__(self, rrepos: ReasoningRepos, provider: LLMProvider | None = None):
        self.rrepos = rrepos
        self.provider = provider

    def build_for_hypothesis(self, project_id: str, opportunity_id: str,
                             hypothesis, max_assumptions: int = 4) -> list[Assumption]:
        """Create (idempotently) ranked Assumption entities for one business
        hypothesis. LLM may propose; fallback guarantees coverage."""
        statements = self._propose(hypothesis)
        existing = {a.statement[:100] for a in
                    self.rrepos.assumptions.all(project_id)}
        out = []
        for stmt in statements[:max_assumptions]:
            if stmt[:100] in existing:
                out.extend(a for a in self.rrepos.assumptions.all(project_id)
                           if a.statement[:100] == stmt[:100])
                continue
            cat = infer_category(stmt)
            a = Assumption(
                project_id=project_id,
                statement=stmt,
                kind="critical" if cat in ("willingness_to_pay", "customer_frequency",
                                           "problem_severity") else "supporting",
                category=cat,
                status="unverified",
                importance=(0.9 if cat in ("willingness_to_pay", "customer_frequency")
                            else 0.7),
                uncertainty=0.8,
                impact_of_failure=(0.9 if cat == "willingness_to_pay" else 0.7),
                ease_of_testing={"problem_severity": 0.8, "customer_frequency": 0.7,
                                 "willingness_to_pay": 0.5, "distribution": 0.4,
                                 "retention": 0.3}.get(cat, 0.5),
                hypothesis_id=hypothesis.id,
                opportunity_id=opportunity_id,
            )
            a.ensure_id()
            self.rrepos.assumptions.save(a)
            out.append(a)
        return out

    def _propose(self, hypothesis) -> list[str]:
        if self.provider is not None:
            from research_engine.prompts.registry import get_prompt
            try:
                spec = get_prompt("query_generator")
                user = (
                    f"Hypothesis ({hypothesis.type}): {hypothesis.statement}\n\n"
                    'List 2-4 assumptions that MUST hold for this hypothesis to be true. '
                    'Respond ONLY with JSON: {"assumptions": ["...", "..."]}')
                from pydantic import BaseModel

                class Out(BaseModel):
                    assumptions: list[str] = []
                parsed, errors = self.provider.structured(spec.system, user, Out)
                if parsed is not None and parsed.assumptions:
                    return [s.strip() for s in parsed.assumptions if s.strip()]
            except Exception:
                pass
        base = {
            "CUSTOMER": ["the target customer experiences this problem frequently",
                         "customers will act to solve the problem"],
            "MARKET": ["current alternatives leave the need substantially unmet",
                       "enough customers exist in the segment to matter"],
            "WILLINGNESS_TO_PAY": ["customers will pay for the improvement",
                                   "the value delivered exceeds the price charged"],
            "DISTRIBUTION": ["the segment can be reached economically",
                             "trust barriers do not block adoption"],
        }
        stmts = base.get(hypothesis.type.upper(), []) + _FALLBACK_ASSUMPTIONS[:2]
        seen, out = set(), []
        for s in stmts:
            if s.lower() not in seen:
                seen.add(s.lower())
                out.append(f"{s[0].upper()}{s[1:]}" if s.islower() or True else s)
        return out[:4]
