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
    # Phase 5 §37: cross-specialist attribution. Empty for intra-domain
    # contradictions; CROSS_DOMAIN_* conflict_types set these. Additive —
    # no second contradiction system.
    specialist_a: str = ""
    specialist_b: str = ""
    domain_difference: str = ""

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)


class Connection(Entity):
    """Cross-domain connection (Phase 5 §22). A proposed link between two
    domain entities; NEVER valid merely because concepts are related."""
    PREFIX: ClassVar[str] = "conn"

    source_domain: str = ""          # e.g. research | technology | startup
    target_domain: str = ""
    source_entity: str = ""          # entity id in its domain store
    target_entity: str = ""
    relationship: str = ""           # CONNECTION_TYPES taxonomy
    rationale: str = ""              # why this link, not just similarity
    alternative_explanations: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    # INV-015: confidence is COMPUTED from linked evidence quality via the
    # canonical aggregator (INV-007); specialists never assert it directly.
    confidence: float = 0.0
    status: str = "PROPOSED"         # PROPOSED|VALIDATED|REJECTED|CONTESTED
    requirements: dict = Field(default_factory=dict)  # {evidence_class: min}

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)
