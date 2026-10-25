"""Business assumption engine.

Fixes a structural gap: business hypotheses previously never received real
`Assumption` entities, leaving the validation designer with nothing to work
from. Here every business hypothesis gets assumptions as first-class rows in
the reasoning store (assumptions2), ranked by the standard priority formula
(importance × uncertainty × impact_of_failure × testability — spec #37).
"""
from __future__ import annotations

import logging
import re

from pydantic import BaseModel

from research_engine.models.reasoning import Assumption
from research_engine.platform.errors import classify
from research_engine.platform.obs_logging import redact
from research_engine.prompts.registry import get_prompt
from research_engine.providers.llm.base import LLMError, LLMProvider
from research_engine.storage.reasoning_repos import ReasoningRepos

log = logging.getLogger(__name__)

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


class _AssumptionListOut(BaseModel):
    assumptions: list[str] = []


class BusinessAssumptionBuilder:
    def __init__(self, rrepos: ReasoningRepos, provider: LLMProvider | None = None):
        self.rrepos = rrepos
        self.provider = provider
        self.last_outcome: dict = {
            "status": "unconfigured" if provider is None else "idle",
            "provider": getattr(getattr(provider, "cfg", None), "provider", "none"),
            "error_category": "",
            "reason": "",
            "fallback_used": False,
        }

    def build_for_hypothesis(self, project_id: str, opportunity_id: str,
                             hypothesis, max_assumptions: int = 4) -> list[Assumption]:
        """Create (idempotently) ranked Assumption entities for one business
        hypothesis. LLM may propose; fallback guarantees coverage."""
        statements = self._propose(hypothesis, max_assumptions=max_assumptions)
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

    def _propose(self, hypothesis, max_assumptions: int = 4) -> list[str]:
        prov_name = getattr(getattr(self.provider, "cfg", None), "provider", "none")
        if self.provider is None:
            self.last_outcome = {
                "status": "unconfigured",
                "provider": "none",
                "error_category": "",
                "reason": "no LLM provider configured; deterministic fallback used",
                "fallback_used": True,
            }
            return self._deterministic_fallback(hypothesis, max_assumptions)

        spec = get_prompt("assumption_generator")
        user = spec.render(
            target_context=f"Hypothesis ({hypothesis.type}): {hypothesis.statement}",
            max_assumptions=str(max_assumptions),
        )
        try:
            parsed, errors = self.provider.structured(spec.system, user, _AssumptionListOut)
        except (LLMError, RuntimeError, OSError, ValueError) as exc:
            cat = classify(exc).value
            safe_reason = redact(str(exc))[:200]
            log.warning(
                "assumption_generator provider %s failed (%s): %s",
                prov_name, cat, safe_reason,
            )
            self.last_outcome = {
                "status": "provider_failed",
                "provider": prov_name,
                "error_category": cat,
                "reason": safe_reason,
                "fallback_used": True,
            }
            return self._deterministic_fallback(hypothesis, max_assumptions)

        if parsed is None:
            self.last_outcome = {
                "status": "invalid_output",
                "provider": prov_name,
                "error_category": "VALIDATION",
                "reason": "; ".join(errors)[:200],
                "fallback_used": True,
            }
            return self._deterministic_fallback(hypothesis, max_assumptions)

        cleaned = [s.strip() for s in parsed.assumptions if s and s.strip()]
        if not cleaned:
            # Legitimate empty response from a working model is recorded distinctly
            # from provider failure or schema failure (P1-3 / INV-012).
            self.last_outcome = {
                "status": "empty_output",
                "provider": prov_name,
                "error_category": "",
                "reason": "model returned zero assumptions",
                "fallback_used": True,
            }
            return self._deterministic_fallback(hypothesis, max_assumptions)

        self.last_outcome = {
            "status": "ok",
            "provider": prov_name,
            "error_category": "",
            "reason": "",
            "fallback_used": False,
        }
        return cleaned[:max_assumptions]

    @staticmethod
    def _deterministic_fallback(hypothesis, max_assumptions: int = 4) -> list[str]:
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
                out.append(f"{s[0].upper()}{s[1:]}")
        return out[:max_assumptions]
