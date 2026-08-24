"""Evidence and Claim models — the atomic units of knowledge.

Evidence = quote-grounded extraction from a specific document location.
Claim    = semantic statement that may be supported by multiple evidence items.
An inference or assumption must never silently become a fact.
"""
from __future__ import annotations

from pydantic import Field

from research_engine.models.base import Entity
from research_engine.models.enums import ClaimKind, EvidenceStatus, SourceType


class NumericFact(Entity):
    """A number is meaningless without metric/unit/period/context."""
    PREFIX: ClassVar[str] = "num"

    metric: str = ""
    value: float | None = None
    value_raw: str = ""          # exactly as written in the source
    unit: str = ""
    currency: str = ""
    period: str = ""
    context: str = ""

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)


class Evidence(Entity):
    PREFIX: ClassVar[str] = "ev"

    claim_text: str = ""
    quote: str = ""
    source_id: str = ""
    document_id: str = ""
    chunk_id: str = ""
    location: str = ""           # "page 7, section 4.2" / "heading X"
    source_url: str = ""
    source_title: str = ""
    source_type: SourceType = SourceType.OTHER
    source_tier: int = 5
    published_date: str | None = None
    retrieved_at: str = ""
    entities: list[str] = Field(default_factory=list)
    numbers: list[NumericFact] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    branch: str = ""             # research branch this evidence serves
    confidence: float = 0.5      # extractor's self-assessed confidence in the extraction
    status: EvidenceStatus = EvidenceStatus.EXTRACTED
    kind: ClaimKind = ClaimKind.FACT
    supports: list[str] = Field(default_factory=list)     # claim ids
    contradicts: list[str] = Field(default_factory=list)  # claim/evidence ids
    notes: list[str] = Field(default_factory=list)
    validation_notes: str = ""
    iteration: int = 0           # which research iteration produced it

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)


class Claim(Entity):
    PREFIX: ClassVar[str] = "clm"

    text: str = ""
    kind: ClaimKind = ClaimKind.FACT
    supported_by: list[str] = Field(default_factory=list)      # evidence ids
    contradicted_by: list[str] = Field(default_factory=list)   # evidence ids
    branch: str = ""
    topic: str = ""
    confidence: float = 0.0    # derived from evidence quality/count, computed not asserted
    dedup_key: str = ""        # normalized text used for dedup
    iteration: int = 0
    notes: list[str] = Field(default_factory=list)

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)
