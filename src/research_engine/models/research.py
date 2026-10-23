"""Research plan, branches, queries, search results, sources."""
from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from research_engine.models.base import Entity
from research_engine.models.enums import BranchCategory, SourceType

# The MEANING of `SearchQuery.results_count` is versioned, because it
# changed: it used to count raw hits and now counts distinct canonical URLs.
# A reader that only sees the number cannot tell which of the two it is
# looking at, and the two differ by roughly a factor of two on a multi-leg
# route. The precedent is INV-010's `score_breakdown.schema_version`.
RESULTS_COUNT_LEGACY_HITS = 1
RESULTS_COUNT_DISTINCT_URLS = 2


class ResearchBranch(Entity):
    PREFIX: ClassVar[str] = "br"

    category: str = BranchCategory.GENERIC.value
    question: str = ""
    importance: float = 0.5          # 0..1
    required_evidence: str = ""      # what would count as an answer
    source_preferences: list[str] = Field(default_factory=list)  # provider names
    status: str = "open"             # open | partially_answered | answered | saturated
    priority: int = 1                # 1 = highest
    # --- Phase 2 branch system ---
    parent_branch_id: str = ""       # hierarchical branching (subbranches)
    strategy: str = ""               # BROAD_SWEEP | FOCUSED_DEEP_DIVE | ...
    coverage_score: float = 0.0      # computed by reasoning/coverage.py
    evidence_count: int = 0
    gap_count: int = 0

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
    # Which meaning `results_count` carries: RESULTS_COUNT_LEGACY_HITS (1,
    # raw hits) or RESULTS_COUNT_DISTINCT_URLS (2, distinct canonical URLs).
    # Constraint: the field is OPTIONAL with the legacy default, so a row
    # written by an older engine still loads - `Entity` is extra="forbid" and
    # an unknown key would make the row unreadable. The reverse is not true
    # (an older engine cannot read a row that carries the new fields), which
    # is the same trade-off `leg_outcomes` makes.
    results_count_schema_version: int = RESULTS_COUNT_LEGACY_HITS
    useful_results: int = 0           # results that produced accepted evidence
    iteration: int = 0
    failed: bool = False               # the provider FAILED (not: it found nothing)
    failure_reason: str = ""          # why it failed, for the audit trail
    # Per-leg audit trail: one entry per route leg, so a leg that resolved to
    # nothing is visible instead of silently contributing zero results.
    # Each entry: {leg, provider, status, hits, error} where status is
    # "hits" | "unconfigured" | "optional_unconfigured" | "failed".
    # Decision: JSON-only field (like results_count), counted in Python, not
    # SQL. It changes the row shape, so an engine older than this one cannot
    # read it back (Entity is extra="forbid").
    leg_outcomes: list[dict] = Field(default_factory=list)
    # The leg names the route did NOT contain: planner preferences outside
    # the leg vocabulary, and legs removed by the route cap. Recorded so a
    # refused source is visible instead of silently absent.
    dropped_legs: list[str] = Field(default_factory=list)

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
