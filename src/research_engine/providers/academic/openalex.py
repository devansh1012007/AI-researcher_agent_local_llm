"""OpenAlex — free scholarly graph API. No key required."""
from __future__ import annotations

import logging

import httpx

from research_engine.providers.academic.base import AcademicProvider, clean_query
from research_engine.providers.search.base import RawSearchHit

log = logging.getLogger(__name__)


class OpenAlexProvider(AcademicProvider):
    name = "openalex"
    BASE = "https://api.openalex.org"

    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout
        # polite pool: contact email improves rate limits; generic value is fine
        self.params = {"mailto": "gar-local-research@example.org"}

    def search(self, query: str, max_results: int = 10) -> list[RawSearchHit]:
        try:
            resp = httpx.get(f"{self.BASE}/works", params={
                **self.params,
                "search": clean_query(query),
                "per-page": min(max_results, 50),
                "sort": "relevance_score:desc",
            }, timeout=self.timeout)
            resp.raise_for_status()
            out = []
            for w in resp.json().get("results", []):
                loc = (w.get("best_oa_location") or {}) or {}
                pdf = loc.get("pdf_url") or ""
                out.append(RawSearchHit(
                    url=w.get("doi") or w.get("id") or "",
                    title=w.get("title") or "",
                    snippet=(w.get("abstract_inverted_index") and
                             self._reconstruct_abstract(w["abstract_inverted_index"])) or "",
                    published_date=str(w.get("publication_date") or w.get("publication_year") or ""),
                    metadata={
                        "provider": self.name,
                        "openalex_id": w.get("id", ""),
                        "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
                        "authors": [a.get("author", {}).get("display_name", "")
                                    for a in w.get("authorships", [])[:8]],
                        "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
                        "year": w.get("publication_year"),
                        "cited_by_count": w.get("cited_by_count"),
                        "pdf_url": pdf,
                        "oa_url": loc.get("landing_page_url") or "",
                        "type": w.get("type", ""),
                    },
                ))
            return out
        except httpx.HTTPError as exc:
            log.warning("openalex search failed: %s", exc)
            return []

    @staticmethod
    def _reconstruct_abstract(inv_index: dict) -> str:
        positions: list[tuple[int, str]] = []
        for word, idxs in inv_index.items():
            for i in idxs:
                positions.append((i, word))
        return " ".join(w for _, w in sorted(positions))[:1500]
