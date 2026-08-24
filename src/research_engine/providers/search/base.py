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


class SearchProvider(ABC):
    name = "base"

    @abstractmethod
    def search(self, query: str, max_results: int = 10) -> list[RawSearchHit]:
        ...

    def is_available(self) -> bool:
        return True
