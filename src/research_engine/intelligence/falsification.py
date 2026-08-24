"""Assumption engine + falsification test designer.

For each opportunity:
  - derive critical assumptions (LLM-assisted, deterministic fallback)
  - design the cheapest falsification test per critical assumption
    with explicit pass/fail conditions and a decision rule

These are decision-support artifacts, NOT proof of viability.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from research_engine.models.startup import FalsificationTest
from research_engine.prompts.registry import get_prompt
from research_engine.providers.llm.base import LLMProvider
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)


class _AssumptionOut(BaseModel):
    assumptions: list[str] = []


class _TestOut(BaseModel):
    assumption: str = ""
    cheapest_test: str = ""
    success_condition: str = ""
    failure_condition: str = ""
    decision_rule: str = ""


class AssumptionEngine:
    def __init__(self, repos: Repositories, provider: LLMProvider | None):
        self.repos = repos
        self.provider = provider

    def critical_assumptions(self, opportunity) -> list[str]:
        """LLM proposes; deterministic template fallback guarantees structure."""
        if self.provider is not None:
            spec = get_prompt("query_generator")  # reuse generic system w/ JSON rule
            user = (
                f"Opportunity:\nproblem: {opportunity.problem}\n"
                f"customer segment: {opportunity.customer_segment}\n"
                f"current alternative: {opportunity.current_alternative}\n\n"
                'List the 3-5 CRITICAL assumptions that must hold for this opportunity to '
                'be viable. Respond ONLY with JSON: {"assumptions": ["...", "..."]}')
            out, errors = self.provider.structured(spec.system, user, _AssumptionOut)
            if out is not None and out.assumptions:
                return [a.strip() for a in out.assumptions if a.strip()][:5]
        # deterministic fallback: universal viability assumptions
        seg = opportunity.customer_segment or "the target customer"
        return [
            f"{seg} experience the problem frequently enough to act on it",
            f"They currently spend meaningful time or money on workarounds",
            f"Existing alternatives ({opportunity.current_alternative}) leave the problem unsolved",
            f"{seg} can pay for a better solution",
            "Distribution to this segment is economically feasible",
        ]

    def design_falsification_tests(self, project_id: str, opportunity,
                                   max_tests: int = 5) -> list[FalsificationTest]:
        tests = []
        for assumption in opportunity.critical_assumptions[:max_tests]:
            t = None
            if self.provider is not None:
                t = self._llm_test(assumption)
            if t is None:
                t = self._template_test(assumption)
            ft = FalsificationTest(project_id=project_id, opportunity_id=opportunity.id, **t)
            ft.ensure_id()
            self.repos.db.upsert("falsification_tests", ft.id, project_id, _dump(ft))
            tests.append(ft)
        if tests:
            opportunity.falsification_tests = [t.id for t in tests]
            self.repos.opportunities.save(opportunity)
        return tests

    def _llm_test(self, assumption: str) -> dict | None:
        from pydantic import BaseModel as BM
        class Out(BM):
            assumption: str = assumption
            cheapest_test: str = ""
            success_condition: str = ""
            failure_condition: str = ""
            decision_rule: str = ""
        system = (
            "You design cheap, decisive falsification tests for startup assumptions.\n"
            "Rules: smallest experiment that could DISPROVE the assumption; numeric "
            "pass/fail thresholds; no vanity metrics.\n"
            'Respond ONLY with JSON: {"assumption": "...", "cheapest_test": "...", '
            '"success_condition": "...", "failure_condition": "...", "decision_rule": '
            '"continue if ... / abandon if ..."}.')
        try:
            out, errors = self.provider.structured(system, f"Assumption: {assumption}", Out)
            if out is not None and out.cheapest_test:
                return out.model_dump()
        except Exception:
            pass
        return None

    @staticmethod
    def _template_test(assumption: str) -> dict:
        return {
            "assumption": assumption,
            "cheapest_test": ("Interview 15-20 target customers about this specific "
                              "assumption; observe their current workflow where possible."),
            "success_condition": ">=40% independently confirm the assumption in detail",
            "failure_condition": "<15% show any sign of it",
            "decision_rule": "continue if success threshold met; modify if between thresholds; abandon if failure condition met",
        }


def _dump(model) -> dict:
    import json
    return json.loads(model.model_dump_json())
