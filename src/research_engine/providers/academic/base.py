"""Academic provider interface."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod

from research_engine.providers.search.base import RawSearchHit


def clean_query(q: str) -> str:
    """Sanitize free-text queries for scholarly APIs (they reject some punctuation)."""
    return re.sub(r"[?\"'`:;|<>]", " ", q or "").strip()[:220]


class AcademicProvider(ABC):
    name = "base"

    @abstractmethod
    def search(self, query: str, max_results: int = 10) -> list[RawSearchHit]:
        ...

    def is_available(self) -> bool:
        return True
