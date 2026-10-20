"""Academic provider interface."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod

from research_engine.providers.search.base import RawSearchHit, SearchProviderError


def clean_query(q: str) -> str:
    """Sanitize free-text queries for scholarly APIs (they reject some punctuation)."""
    return re.sub(r"[?\"'`:;|<>]", " ", q or "").strip()[:220]


class AcademicProvider(ABC):
    name = "base"

    @abstractmethod
    def search(self, query: str, max_results: int = 10) -> list[RawSearchHit]:
        """Return hits for the query.

        Returns an empty list when the search succeeded and found nothing.
        Raises SearchProviderError when the search could not be completed
        (transport error, rate limit, unparseable response) — the same
        contract as SearchProvider, so a failed academic lookup is never
        mistaken for an empty result.
        """
        ...

    def is_available(self) -> bool:
        return True
