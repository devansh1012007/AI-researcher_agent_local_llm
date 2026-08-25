"""Startup opportunity schema — Phase 1 stores the structure; generation is deferred.

The engine will never let observed evidence silently become a market claim:
kind separation (FACT/INFERENCE/ASSUMPTION) is enforced upstream in Claim.
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from research_engine.models.base import Entity


class Opportunity(Entity):
    PREFIX: ClassVar[str] = "opp"

    customer_segment: str = ""
    job_to_be_done: str = ""
    problem: str = ""
    severity: float = 0.0           # 0..1, evidence-derived (see scoring)
    frequency: float = 0.0
    current_alternative: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    market_signal_evidence_ids: list[str] = Field(default_factory=list)
    competitor_names: list[str] = Field(default_factory=list)
    why_now: list[str] = Field(default_factory=list)          # each item must cite change evidence
    distribution: list[str] = Field(default_factory=list)
    pricing_evidence_ids: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    critical_assumptions: list[str] = Field(default_factory=list)
    secondary_assumptions: list[str] = Field(default_factory=list)
    falsification_tests: list[str] = Field(default_factory=list)
    notes: str = ""
    confidence: float = 0.0
    # transparent score breakdown (spec #39) - never an opaque number
    score_breakdown: dict = Field(default_factory=dict)
    # extensible taxonomy classification (Phase 5 spec #33):
    # workflow_automation | vertical_saas | marketplace | ... (see policies.opportunity_type)
    opportunity_type: str = ""

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)

    @property
    def customer(self) -> str:
        return self.customer_segment
