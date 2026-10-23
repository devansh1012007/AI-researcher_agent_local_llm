"""Source routing: match query/branch to appropriate providers. Configurable."""
from __future__ import annotations

from dataclasses import dataclass, field

from research_engine.models.enums import SourceType


@dataclass(frozen=True)
class RouteLeg:
    """One leg of a branch's search: which provider, and how to bias the query.

    `provider` is the registry key to call. `query_suffix` is appended to the
    branch's query text so each leg searches a genuinely different slice of
    the corpus - without it, two legs on the same provider and query return
    the identical cached hit set, which both double-counts results and
    destroys per-leg attribution.

    `optional` marks a leg whose provider is only registered when the
    operator configures it (semantic_scholar is not in the default academic
    provider list). It has an observable effect: an optional leg that is not
    registered is reported as `optional_unconfigured`, a required leg that is
    not registered as `unconfigured`. Neither is a failure (INV-012) and
    neither is a silent zero.
    """
    provider: str
    query_suffix: str = ""
    optional: bool = False
    # The vocabulary name of this leg ("web", "forum", "openalex", ...).
    name: str = ""


@dataclass
class Route:
    legs: list[RouteLeg] = field(default_factory=list)
    # The names this route does NOT contain: preference names outside the leg
    # vocabulary, plus any leg removed by the _MAX_LEGS cap.
    # Decision: the drop is recorded, not silent.
    # Why: a planner that asked for "github" or "reddit" used to see the name
    # vanish with no trace, so a mis-planned route looked exactly like a
    # planned one.
    # Constraint: the entries are leg NAMES (never providers), and they are
    # recorded by the retrieval worker on the query row, so the drop is
    # visible in a persisted artefact and not only in memory.
    dropped_legs: list[str] = field(default_factory=list)


# Web-search refinements: same provider, different query bias.
# Measured against the live DuckDuckGo endpoint (2026-10-22) with the repo's
# own DuckDuckGoProvider, in one run whose control query
# "battery thermal management" returned 5 hits:
#   "... site:reddit.com OR site:news.ycombinator.com OR site:stackoverflow.com"
#       -> 5 hits (stackoverflow.com, news.ycombinator.com)
#   "... site:.gov"                   -> 5 hits (nlr.gov, nasa.gov)
#   "... site:docs OR site:developer" -> 0 hits (0 of 3 attempts)
#   "... documentation OR tutorial OR reference" -> 5 hits
# Decision: the documentation leg uses a KEYWORD bias, not a `site:` operator.
# Why: `site:` takes a DOMAIN. "docs" and "developer" are not domains, so the
# operator matches nothing and the leg is a silent zero again - the exact
# defect this map exists to remove. The two `site:` operators above WERE
# verified against the live endpoint; the documentation leg was not, and its
# first form did not work.
# Constraint: the bias must stay topic-general (the leg has to work for a
# robotics question and a battery question alike), so it cannot name a
# software-only domain either.
_WEB_FORUM = " site:reddit.com OR site:news.ycombinator.com OR site:stackoverflow.com"
_WEB_GOV = " site:.gov"
_WEB_DOCS = " documentation OR tutorial OR reference"

_LEGS: dict[str, RouteLeg] = {
    "web": RouteLeg("web", name="web"),
    "openalex": RouteLeg("openalex", name="openalex"),
    "crossref": RouteLeg("crossref", name="crossref"),
    "arxiv": RouteLeg("arxiv", name="arxiv"),
    # Optional: Semantic Scholar is not in the default academic provider
    # list, so its absence is a deliberate configuration state.
    "semantic_scholar": RouteLeg("semantic_scholar", optional=True,
                                 name="semantic_scholar"),
    "documentation": RouteLeg("web", _WEB_DOCS, name="documentation"),
    "government": RouteLeg("web", _WEB_GOV, name="government"),
    "forum": RouteLeg("web", _WEB_FORUM, name="forum"),
    "company": RouteLeg("web", " company pricing vendor", name="company"),
}


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

# The closed vocabulary of leg names a branch may name. Anything else is
# dropped rather than becoming a silent dead leg (an LLM planner can emit
# arbitrary strings here).
LEG_NAMES: frozenset[str] = frozenset(_LEGS)

# Maximum number of legs one branch may fan out to.
# Decision: a route is capped so one branch cannot issue an unbounded number
# of provider calls per query.
# Why: the preference path can merge an arbitrary number of planner-supplied
# legs with the branch's defaults; without a cap a single branch could drive
# an unbounded fan-out of provider calls.
# Constraint: no default route exceeds the cap, so the default path is never
# truncated - a test pins that. Names removed by the cap are recorded in
# `Route.dropped_legs`, never dropped silently.
_MAX_LEGS = 4

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
    """Resolve a branch category (+ optional LLM-provided preferences) to legs.

    Preferences are validated against the closed leg vocabulary. An unknown
    name is dropped, NOT merged: a leg naming a provider that does not exist
    resolves to nothing and silently contributes zero results, which is the
    defect class this map exists to prevent.

    Every name that does NOT make it into the route is recorded in
    `Route.dropped_legs`, so "the planner asked for something we do not have"
    is visible instead of silent.
    """
    base = DEFAULT_ROUTES.get(branch_category, DEFAULT_ROUTES["GENERIC"])
    prefs: list[str] = []
    dropped: list[str] = []
    for raw in (source_preferences or []):
        name = raw.lower().strip()
        if not name:
            continue
        if name not in LEG_NAMES:
            dropped.append(name)
        elif name not in prefs:
            # Decision: a repeated preference is taken once.
            # Why: the same leg twice means the same provider query twice on
            # the same text - the double-count defect this map exists to fix.
            prefs.append(name)
    if prefs:
        # preferences take priority but keep sensible defaults behind them
        merged = prefs + [p for p in base if p not in prefs]
    else:
        merged = list(base)
    # Decision: the cap applies to the default path too, not only to the
    # preferences path.
    # Why: one branch must not fan out into an unbounded number of provider
    # calls per query, whichever path produced the legs.
    # Constraint: no base route exceeds the cap (a test pins this), so the
    # default path is never truncated in practice; when it is, the removed
    # names are recorded in `dropped_legs`.
    kept = merged[:_MAX_LEGS]
    dropped.extend(name for name in merged[_MAX_LEGS:] if name not in dropped)
    return Route(legs=[_LEGS[name] for name in kept], dropped_legs=dropped)


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
