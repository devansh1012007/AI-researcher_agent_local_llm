"""Research plan, branches, queries, search results, sources."""
from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from research_engine.models.base import Entity
from research_engine.models.enums import BranchCategory, SourceType


class ResearchBranch(Entity):
    PREFIX: ClassVar[str] = "br"

    category: BranchCategory = BranchCategory.GENERIC
    question: str = ""
    importance: float = 0.5          # 0..1
    required_evidence: str = ""      # what would count as an answer
    source_preferences: list[str] = Field(default_factory=list)  # provider names
    status: str = "open"             # open | partially_answered | answered | saturated
    priority: int = 1                # 1 = highest

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)


class ResearchPlan(Entity):
    PREFIX: ClassVar[str] = "plan"

    objective: str = ""
    branches: list[ResearchBranch] = Field(default_factory=list)
    version: int = 1

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)


class SearchQuery(Entity):
    PREFIX: ClassVar[str] = "q"

    text: str = ""
    branch: str = ""                  # branch id
    reason: str = ""                  # why this query exists (traceability)
    kind: str = "primary"             # primary|synonym|technical|contradiction|date_filtered|source_specific
    priority: float = 0.5
    expected_information_gain: float = 0.0   # computed heuristic score
    executed: bool = False
    results_count: int = 0
    useful_results: int = 0           # results that produced accepted evidence
    iteration: int = 0

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)


class SearchResult(Entity):
    PREFIX: ClassVar[str] = "sr"

    query_id: str = ""
    url: str = ""
    canonical_url: str = ""
    title: str = ""
    snippet: str = ""
    provider: str = ""               # duckduckgo | openalex | crossref | arxiv ...
    published_date: str | None = None
    metadata: dict = Field(default_factory=dict)

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)


class Source(Entity):
    PREFIX: ClassVar[str] = "src"

    url: str = ""
    canonical_url: str = ""
    title: str = ""
    domain: str = ""
    source_type: SourceType = SourceType.OTHER
    publisher: str = ""
    author: str = ""
    publication_date: str | None = None
    retrieval_date: str = ""
    source_tier: int = 5             # prior about quality, NOT proof of correctness
    content_hash: str = ""
    content_status: str = "DISCOVERED"
    http_status: int | None = None
    content_type: str = ""
    language: str = ""
    doi: str = ""
    citation_count: int | None = None
    rejected_reason: str = ""
    query_ids: list[str] = Field(default_factory=list)

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)
