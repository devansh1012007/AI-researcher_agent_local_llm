"""Startup-mode knowledge entities."""
from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from research_engine.models.base import Entity


class CustomerSegment(Entity):
    PREFIX: ClassVar[str] = "seg"
    name: str = ""
    job_to_be_done: str = ""
    decision_maker: str = ""        # user != buyer (spec #30)
    buyer: str = ""
    switching_friction: str = ""
    notes: list[str] = Field(default_factory=list)


class PainPoint(Entity):
    PREFIX: ClassVar[str] = "pain"
    statement: str = ""
    kind: str = "stated"            # stated | observed | inferred  (NOT equivalent)
    segment: str = ""
    frequency_signals: int = 0      # independent mentions observed
    severity_hint: str = ""
    current_alternative: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class Competitor(Entity):
    PREFIX: ClassVar[str] = "comp"
    name: str = ""
    product: str = ""
    target_segment: str = ""
    positioning: str = ""
    geography: str = ""
    business_model: str = ""
    # traction kept SEPARATE from existence (spec #78)
    funding_signal: str = ""
    customer_evidence: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class PriceObservation(Entity):
    PREFIX: ClassVar[str] = "price"
    company: str = ""
    product: str = ""
    amount_raw: str = ""            # exactly as written in source
    currency: str = "USD"
    billing_period: str = ""        # monthly | annual | one_time | usage
    tier: str = ""
    included_limits: str = ""
    segment: str = ""
    geography: str = ""
    observed_date: str = ""
    source_id: str = ""
    evidence_id: str = ""

    def describe(self) -> str:
        return f"{self.amount_raw} {self.currency}/{self.billing_period or '?'} ({self.tier or 'base tier'})"


class MarketSignal(Entity):
    PREFIX: ClassVar[str] = "sig"
    kind: str = ""                  # funding|hiring|job_posting|regulation|launch|pricing_change|
                                    # complaint|search_interest|acquisition|infrastructure
    description: str = ""
    direction: str = ""             # growing|shrinking|neutral
    date: str = ""
    geography: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class FalsificationTest(Entity):
    PREFIX: ClassVar[str] = "ftest"
    opportunity_id: str = ""
    assumption: str = ""
    cheapest_test: str = ""
    success_condition: str = ""
    failure_condition: str = ""
    decision_rule: str = ""         # continue | modify | abandon thresholds
    estimated_cost: str = ""
