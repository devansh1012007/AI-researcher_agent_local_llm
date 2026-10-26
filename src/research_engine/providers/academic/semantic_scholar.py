"""Semantic Scholar Graph API. Works keyless (rate-limited); optional API key."""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from research_engine.core.http_policy import EgressPolicy
from research_engine.providers.academic.base import AcademicProvider, clean_query
from research_engine.providers.search.base import RawSearchHit, SearchProviderError

log = logging.getLogger(__name__)

_FIELDS = "title,abstract,year,venue,externalIds,url,citationCount,authors"


class SemanticScholarProvider(AcademicProvider):
    name = "semantic_scholar"
    BASE = "https://api.semanticscholar.org/graph/v1"

    def __init__(self, api_key: str = "", timeout: float = 20.0, policy: EgressPolicy | None = None):
        self.timeout = timeout
        self.headers = {"x-api-key": api_key} if api_key else {}
        self.policy = policy

    def search(self, query: str, max_results: int = 10) -> list[RawSearchHit]:
        try:
            url = f"{self.BASE}/paper/search"
            if self.policy is not None:
                self.policy.require(urlparse(url).hostname, "semantic_scholar search")
            resp = httpx.get(url, params={
                "query": clean_query(query), "limit": min(max_results, 100), "fields": _FIELDS,
            }, headers=self.headers, timeout=self.timeout)
            if resp.status_code == 429:
                log.warning("semantic scholar rate limited")
                raise SearchProviderError("semantic scholar: rate limited (429)")
            resp.raise_for_status()
            out = []
            for w in resp.json().get("data", []):
                doi = (w.get("externalIds") or {}).get("DOI", "")
                out.append(RawSearchHit(
                    url=w.get("url") or (f"https://doi.org/{doi}" if doi else ""),
                    title=w.get("title") or "",
                    snippet=(w.get("abstract") or "")[:1500],
                    published_date=str(w.get("year")) if w.get("year") else None,
                    metadata={
                        "provider": self.name,
                        "doi": doi,
                        "authors": [a.get("name", "") for a in (w.get("authors") or [])[:8]],
                        "venue": w.get("venue", ""),
                        "cited_by_count": w.get("citationCount"),
                    },
                ))
            return out
        except httpx.HTTPError as exc:
            log.warning("semantic scholar search failed: %s", exc)
            raise SearchProviderError(f"semantic scholar: {exc}") from exc
