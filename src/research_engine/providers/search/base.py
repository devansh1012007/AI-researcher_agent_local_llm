"""Search provider interfaces. Normalized results across all providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class RawSearchHit:
    url: str
    title: str
    snippet: str = ""
    published_date: str | None = None
    metadata: dict = field(default_factory=dict)


class SearchProviderError(RuntimeError):
    """The provider could not complete the request.

    Decision: a provider RAISES on failure and returns an EMPTY LIST only
    for a successful search that found nothing.
    Why: INV-012 requires a failed operation to be distinguishable from an
    empty result. Every provider used to swallow the error and return [], so
    a total search outage was indistinguishable from a search that found
    nothing — and the run was reported as CONVERGED.
    Constraint: callers that isolate a provider failure (the retrieval
    worker) must catch this and RECORD it; they must not let it kill the
    loop, and they must not turn it back into an empty result.
    """


class SearchProvider(ABC):
    name = "base"

    @abstractmethod
    def search(self, query: str, max_results: int = 10) -> list[RawSearchHit]:
        """Return hits for the query.

        Returns an empty list when the search succeeded and found nothing.
        Raises SearchProviderError when the search could not be completed.
        """
        ...

    def is_available(self) -> bool:
        return True
