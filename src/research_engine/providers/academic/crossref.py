"""Crossref — DOI metadata API. No key required."""
from __future__ import annotations

import logging

import httpx

from research_engine.providers.academic.base import AcademicProvider, clean_query
from research_engine.providers.search.base import RawSearchHit

log = logging.getLogger(__name__)


class CrossrefProvider(AcademicProvider):
    name = "crossref"
    BASE = "https://api.crossref.org"

    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout
        self.headers = {"User-Agent": "GAR-ResearchBot/0.1 (mailto:gar-local-research@example.org)"}

    def search(self, query: str, max_results: int = 10) -> list[RawSearchHit]:
        try:
            resp = httpx.get(f"{self.BASE}/works", params={
                "query.bibliographic": clean_query(query),
                "rows": min(max_results, 50),
                "select": "DOI,title,author,issued,container-title,abstract,URL,is-referenced-by-count,type",
            }, headers=self.headers, timeout=self.timeout)
            resp.raise_for_status()
            items = resp.json().get("message", {}).get("items", [])
            out = []
            for w in items:
                title = (w.get("title") or [""])[0]
                date_parts = ((w.get("issued") or {}).get("date-parts") or [[None]])[0]
                pub = "-".join(str(d) for d in date_parts if d)
                abstract = (w.get("abstract") or "").replace("<jats:p>", "").replace("</jats:p>", "")
                abstract = abstract.replace("<jats:title>", "").replace("</jats:title>", "")[:1500]
                out.append(RawSearchHit(
                    url=w.get("URL") or f"https://doi.org/{w.get('DOI', '')}",
                    title=title,
                    snippet=abstract,
                    published_date=pub or None,
                    metadata={
                        "provider": self.name,
                        "doi": w.get("DOI", ""),
                        "authors": [f"{a.get('given','')} {a.get('family','')}".strip()
                                    for a in (w.get("author") or [])[:8]],
                        "venue": (w.get("container-title") or [""])[0],
                        "cited_by_count": w.get("is-referenced-by-count"),
                        "type": w.get("type", ""),
                    },
                ))
            return out
        except httpx.HTTPError as exc:
            log.warning("crossref search failed: %s", exc)
            return []
