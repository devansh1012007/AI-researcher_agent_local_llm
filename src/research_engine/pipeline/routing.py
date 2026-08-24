"""Source routing: match query/branch to appropriate providers. Configurable."""
from __future__ import annotations

from dataclasses import dataclass

from research_engine.models.enums import BranchCategory, SourceType


@dataclass
class Route:
    providers: list[str]          # search provider names ("web") + academic provider names


DEFAULT_ROUTES: dict[str, list[str]] = {
    "FOUNDATIONS": ["openalex", "arxiv", "crossref", "web"],
    "CURRENT_STATE": ["web", "documentation", "openalex"],
    "METHODS": ["openalex", "arxiv", "semantic_scholar", "web"],
    "COMPETING_APPROACHES": ["openalex", "arxiv", "web"],
    "EVIDENCE": ["openalex", "crossref", "semantic_scholar"],
    "BENCHMARKS": ["openalex", "arxiv", "web", "documentation"],
    "LIMITATIONS": ["openalex", "arxiv", "web"],
    "CONTRADICTIONS": ["openalex", "semantic_scholar", "web"],
    "APPLICATIONS": ["web", "documentation", "openalex"],
    "OPEN_PROBLEMS": ["arxiv", "openalex", "web"],
    "MARKET": ["web"],
    "CUSTOMERS": ["web"],
    "PAIN": ["web", "forum"],
    "ALTERNATIVES": ["web"],
    "COMPETITORS": ["web"],
    "PRICING": ["web"],
    "DISTRIBUTION": ["web"],
    "REGULATIONS": ["web", "government"],
    "TECHNOLOGY": ["web", "openalex", "arxiv"],
    "FUNDING": ["web"],
    "TIMING": ["web"],
    "RISKS": ["web"],
    "GENERIC": ["web", "openalex"],
}

# URL patterns -> source type classification (deterministic pre-classification)
_DOMAIN_TYPE_HINTS: list[tuple[str, SourceType]] = [
    (".gov", SourceType.GOVERNMENT),
    (".edu", SourceType.RESEARCH_PAPER),
    ("arxiv.org", SourceType.RESEARCH_PAPER),
    ("doi.org", SourceType.RESEARCH_PAPER),
    ("semanticscholar.org", SourceType.RESEARCH_PAPER),
    ("openreview.net", SourceType.RESEARCH_PAPER),
    ("nature.com", SourceType.RESEARCH_PAPER),
    ("ieee.org", SourceType.RESEARCH_PAPER),
    ("acm.org", SourceType.RESEARCH_PAPER),
    ("springer.com", SourceType.RESEARCH_PAPER),
    ("sciencedirect.com", SourceType.RESEARCH_PAPER),
    ("sec.gov", SourceType.FINANCIAL_FILING),
    ("crunchbase.com", SourceType.INDUSTRY_REPORT),
    ("reddit.com", SourceType.FORUM),
    ("news.ycombinator.com", SourceType.FORUM),
    ("stackoverflow.com", SourceType.FORUM),
    ("quora.com", SourceType.FORUM),
    ("medium.com", SourceType.BLOG),
    ("substack.com", SourceType.BLOG),
    ("docs.", SourceType.DOCUMENTATION),
    ("developer.mozilla.org", SourceType.DOCUMENTATION),
    ("github.com", SourceType.DOCUMENTATION),
]


def classify_source(url: str) -> tuple[SourceType, int]:
    """Deterministic first-pass classification; returns (type, tier)."""
    from research_engine.models.enums import TIER_BY_SOURCE_TYPE
    url_l = url.lower()
    stype = SourceType.SEARCH_RESULT
    for pattern, t in _DOMAIN_TYPE_HINTS:
        if pattern in url_l:
            stype = t
            break
    return stype, TIER_BY_SOURCE_TYPE[stype]


def route_for(branch_category: str, source_preferences: list[str] | None = None) -> Route:
    prefs = [p.lower() for p in (source_preferences or []) if p]
    base = DEFAULT_ROUTES.get(branch_category, DEFAULT_ROUTES["GENERIC"])
    if prefs:
        # preferences take priority but keep sensible defaults behind them
        merged = [p for p in prefs if p != "forum"] + [p for p in base if p not in prefs]
        return Route(providers=merged[:4])
    return Route(providers=base)


class ProviderRegistry:
    """Holds live provider instances by name."""

    def __init__(self):
        self._search = {}
        self._academic = {}

    def register_search(self, name: str, provider) -> None:
        self._search[name] = provider

    def register_academic(self, name: str, provider) -> None:
        self._academic[name] = provider

    def get_search(self, name: str):
        return self._search.get(name)

    def get_any(self, name: str):
        return self._search.get(name) or self._academic.get(name)
