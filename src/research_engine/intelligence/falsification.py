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
from research_engine.platform.errors import classify
from research_engine.platform.obs_logging import redact
from research_engine.prompts.registry import get_prompt
from research_engine.providers.llm.base import LLMError, LLMProvider
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
        self.last_outcome: dict = {
            "status": "unconfigured" if provider is None else "idle",
            "provider": getattr(getattr(provider, "cfg", None), "provider", "none"),
            "error_category": "",
            "reason": "",
            "fallback_used": False,
        }

    def critical_assumptions(self, opportunity) -> list[str]:
        """LLM proposes; deterministic template fallback guarantees structure."""
        prov_name = getattr(getattr(self.provider, "cfg", None), "provider", "none")
        if self.provider is not None:
            spec = get_prompt("assumption_generator")
            target_ctx = (
                f"Opportunity:\nproblem: {opportunity.problem}\n"
                f"customer segment: {opportunity.customer_segment}\n"
                f"current alternative: {opportunity.current_alternative}"
            )
            user = spec.render(target_context=target_ctx, max_assumptions="5")
            try:
                out, errors = self.provider.structured(spec.system, user, _AssumptionOut)
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
                return self._fallback_assumptions(opportunity)
            if out is None:
                self.last_outcome = {
                    "status": "invalid_output",
                    "provider": prov_name,
                    "error_category": "VALIDATION",
                    "reason": "; ".join(errors)[:200],
                    "fallback_used": True,
                }
                return self._fallback_assumptions(opportunity)
            cleaned = [a.strip() for a in out.assumptions if a and a.strip()][:5]
            if not cleaned:
                self.last_outcome = {
                    "status": "empty_output",
                    "provider": prov_name,
                    "error_category": "",
                    "reason": "model returned zero assumptions",
                    "fallback_used": True,
                }
                return self._fallback_assumptions(opportunity)
            self.last_outcome = {
                "status": "ok",
                "provider": prov_name,
                "error_category": "",
                "reason": "",
                "fallback_used": False,
            }
            return cleaned
        self.last_outcome = {
            "status": "unconfigured",
            "provider": "none",
            "error_category": "",
            "reason": "no LLM provider configured; deterministic fallback used",
            "fallback_used": True,
        }
        return self._fallback_assumptions(opportunity)

    @staticmethod
    def _fallback_assumptions(opportunity) -> list[str]:
        seg = opportunity.customer_segment or "the target customer"
        return [
            f"{seg} experience the problem frequently enough to act on it",
            "They currently spend meaningful time or money on workarounds",
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
            else:
                self.last_outcome = {
                    "status": "unconfigured",
                    "provider": "none",
                    "error_category": "",
                    "reason": "no LLM provider configured; deterministic fallback used",
                    "fallback_used": True,
                }
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
        prov_name = getattr(getattr(self.provider, "cfg", None), "provider", "none")
        spec = get_prompt("falsification_designer")
        user = spec.render(assumption=assumption)
        try:
            out, errors = self.provider.structured(spec.system, user, _TestOut)
        except (LLMError, RuntimeError, OSError, ValueError) as exc:
            cat = classify(exc).value
            safe_reason = redact(str(exc))[:200]
            log.warning(
                "falsification_designer provider %s failed (%s): %s",
                prov_name, cat, safe_reason,
            )
            self.last_outcome = {
                "status": "provider_failed",
                "provider": prov_name,
                "error_category": cat,
                "reason": safe_reason,
                "fallback_used": True,
            }
            return None
        if out is None:
            self.last_outcome = {
                "status": "invalid_output",
                "provider": prov_name,
                "error_category": "VALIDATION",
                "reason": "; ".join(errors)[:200],
                "fallback_used": True,
            }
            return None
        if not out.cheapest_test.strip():
            self.last_outcome = {
                "status": "empty_output",
                "provider": prov_name,
                "error_category": "",
                "reason": "model returned empty cheapest_test",
                "fallback_used": True,
            }
            return None
        self.last_outcome = {
            "status": "ok",
            "provider": prov_name,
            "error_category": "",
            "reason": "",
            "fallback_used": False,
        }
        d = out.model_dump()
        d["assumption"] = out.assumption or assumption
        return d

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
