"""Analysis models: gaps and contradictions."""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from research_engine.models.base import Entity
from research_engine.models.enums import GapCategory, Severity


class RecommendedQuery(BaseModel):
    text: str = ""
    reason: str = ""


class Gap(Entity):
    PREFIX: ClassVar[str] = "gap"

    description: str = ""
    category: GapCategory = GapCategory.MISSING_INFORMATION
    importance: float = 0.5
    severity: Severity = Severity.MEDIUM
    evidence_needed: str = ""
    branch: str = ""
    recommended_queries: list[RecommendedQuery] = Field(default_factory=list)
    resolved: bool = False
    resolved_by_query_ids: list[str] = Field(default_factory=list)
    iteration_found: int = 0
    iteration_resolved: int | None = None

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)


class Contradiction(Entity):
    PREFIX: ClassVar[str] = "con"

    claim_a_id: str = ""
    claim_b_id: str = ""
    statement_a: str = ""
    statement_b: str = ""
    explanation: str = ""              # possible explanation; NOT a resolution
    source_quality_note: str = ""      # comparison of supporting source tiers
    follow_up_query: str = ""
    resolved: bool = False             # only user/resolution step sets this
    # INVARIANT-009 (P0-08): both sides identified explicitly. Claim links
    # may be empty ONLY alongside evidence-side links; fully-unlinked rows
    # are malformed historical data (conflict_type=LEGACY_UNLINKED).
    conflict_type: str = "DIRECT_CONTRADICTION"
    evidence_a_ids: list[str] = Field(default_factory=list)
    evidence_b_ids: list[str] = Field(default_factory=list)

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)
