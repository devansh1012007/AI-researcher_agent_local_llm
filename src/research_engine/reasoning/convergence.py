"""Convergence detection: deterministic signals first, LLM as tiebreaker.

Never let an LLM's "dissatisfaction" drive endless search: budgets are hard stops.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from research_engine.core.budget import Budget
from research_engine.models.enums import StopReason
from research_engine.prompts.registry import get_prompt
from research_engine.providers.llm.base import LLMProvider
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


@dataclass
class ConvergenceDecision:
    should_stop: bool
    stop_reason: StopReason | None = None
    rationale: str = ""


class _ConvergenceOut(BaseModel):
    should_continue: bool = True
    confidence: float = 0.5
    reasoning: str = ""
    dominant_signal: str = "new_information_rate"


class ConvergenceAnalyzer:
    def __init__(self, cfg, provider: LLMProvider | None = None):
        self.cfg = cfg
        self.provider = provider

    def evaluate(self, project, budget: Budget, stats: dict) -> ConvergenceDecision:
        r = self.cfg.research
        exhausted = budget.exhausted()
        if exhausted:
            return ConvergenceDecision(True, StopReason.BUDGET_EXHAUSTED,
                                       f"budget exhausted: {exhausted}")
        if budget.usage.iterations_used >= r.max_iterations:
            return ConvergenceDecision(True, StopReason.MAX_ITERATIONS,
                                       f"reached max_iterations={r.max_iterations}")
        # deterministic convergence signals
        total_ev = stats.get("total_evidence", 0)
        new_ev = stats.get("new_evidence", 0)
        high_gaps = stats.get("high_importance_gaps", 0)
        dup_rate = stats.get("duplicate_rate", 0.0)
        rej_rate = stats.get("rejection_rate", 0.0)
        fetch_successes = stats.get("fetch_successes")
        fetch_failures = stats.get("fetch_failures", 0)
        queries_executed = stats.get("queries_executed", 0)

        # P0-04 INVARIANT-006: failure is not saturation. Degradation means
        # retrieval ATTEMPTED and FAILED (network/provider), not merely
        # "nothing new" (which cached-duplicate silence also produces).
        if (new_ev == 0 and fetch_failures > 0 and queries_executed > 0):
            return ConvergenceDecision(
                True, StopReason.PROVIDER_DEGRADED,
                f"{queries_executed} queries ran; {fetch_failures} fetch "
                "failures and 0 new evidence this iteration")
        if total_ev > 0 and rej_rate > r.duplicate_rate_converged:
            # hallucinated-extraction pathology: stop as DEGRADED for diagnosis,
            # never report as converged research
            return ConvergenceDecision(
                True, StopReason.PROVIDER_DEGRADED,
                f"verification rejection rate {rej_rate:.2f} exceeds threshold — "
                "extraction quality degraded")
        if total_ev >= 10 and new_ev / max(1, total_ev) < r.new_evidence_threshold:
            return ConvergenceDecision(True, StopReason.CONVERGED,
                                       f"new evidence rate {new_ev}/{total_ev} below threshold")
        if total_ev > 0 and dup_rate > r.duplicate_rate_converged:
            return ConvergenceDecision(True, StopReason.CONVERGED,
                                       f"true duplicate rate {dup_rate:.2f} too high")
        if total_ev >= 10 and high_gaps == 0 and stats.get("new_claims", 0) == 0:
            return ConvergenceDecision(True, StopReason.NO_HIGH_VALUE_GAPS,
                                       "no high-importance gaps and no new claims")
        # LLM tiebreaker (advisory only; cannot override budgets)
        if self.provider is not None and total_ev >= 8:
            spec = get_prompt("convergence_analyzer")
            user = spec.render(
                objective=stats.get("objective", ""), iteration=str(stats.get("iteration", "?")),
                max_iterations=str(r.max_iterations), new_evidence=str(new_ev),
                new_claims=str(stats.get("new_claims", 0)), duplicate_rate=f"{dup_rate:.2f}",
                high_gaps=str(high_gaps), total_evidence=str(total_ev),
                domains=str(stats.get("domains", 0)))
            out, errors = self.provider.structured(spec.system, user, _ConvergenceOut)
            if out is not None and not out.should_continue and high_gaps == 0:
                return ConvergenceDecision(True, StopReason.CONVERGED,
                                           f"model: {out.reasoning[:200]}")
        return ConvergenceDecision(False, rationale="continuing: valuable gaps remain")
