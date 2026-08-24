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

    customer: str = ""
    problem: str = ""
    current_alternative: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    market_signal_evidence_ids: list[str] = Field(default_factory=list)
    competitor_names: list[str] = Field(default_factory=list)
    why_now: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    critical_assumptions: list[str] = Field(default_factory=list)
    validation_tests: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    notes: str = ""

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)
