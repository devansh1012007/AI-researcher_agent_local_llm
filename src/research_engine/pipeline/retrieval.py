"""Retrieval worker: execute routed queries, normalize results, create sources.

Parallelizes IO-bound search/fetch with a bounded thread pool; never parallelizes LLM work.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from research_engine.core.config import AppConfig
from research_engine.core.ids import url_canonicalize
from research_engine.models.enums import ContentStatus
from research_engine.models.research import SearchQuery, SearchResult, Source
from research_engine.pipeline.routing import ProviderRegistry, classify_source, route_for
from research_engine.storage.cache import KVCache, cache_key
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)


class RetrievalWorker:
    def __init__(self, cfg: AppConfig, repos: Repositories,
                 registry: ProviderRegistry, search_cache: KVCache | None = None):
        self.cfg = cfg
        self.repos = repos
        self.registry = registry
        self.search_cache = search_cache or KVCache(
            Path(cfg.storage.data_dir) / "_global" / "search_cache.sqlite")

    def execute_queries(self, project_id: str, queries: list[SearchQuery],
                        budget_left: int) -> tuple[list[SearchQuery], list[Source]]:
        """Run up to budget_left queries (parallel IO), return executed queries + new sources."""
        to_run = [q for q in queries if not q.executed][:max(0, budget_left)]
        new_sources: dict[str, Source] = {}
        with ThreadPoolExecutor(max_workers=self.cfg.resources.max_parallel_fetches) as pool:
            futures = {pool.submit(self._execute_one, project_id, q): q for q in to_run}
            for fut in as_completed(futures):
                q = futures[fut]
                try:
                    hits = fut.result()
                except Exception as exc:  # isolation: one query failure never kills the loop
                    log.warning("query %s failed: %s", q.id, exc)
                    hits = []
                q.executed = True
                q.results_count = len(hits)
                for hit in hits:
                    src = self._register_result(project_id, q.id, hit)
                    if src is not None:
                        new_sources[src.canonical_url] = src
                        q.useful_results += 0  # updated later by evidence worker feedback
                self.repos.queries.save(q)
        return to_run, list(new_sources.values())

    def _cached_search(self, provider_name: str, query_text: str):
        key = cache_key(provider_name, query_text)
        cached = self.search_cache.get(key)
        if cached is not None:
            from research_engine.providers.search.base import RawSearchHit
            return [RawSearchHit(**h) for h in cached]
        provider = self.registry.get_any(provider_name)
        if provider is None:
            return []
        try:
            hits = provider.search(query_text, max_results=self.cfg.search.results_per_query)
        except Exception as exc:
            log.warning("provider %s failed: %s", provider_name, exc)
            return []
        self.search_cache.put(
            key, [{"url": h.url, "title": h.title, "snippet": h.snippet,
                   "published_date": h.published_date, "metadata": h.metadata} for h in hits],
            ttl_hours=self.cfg.search.cache_ttl_hours)
        return hits

    def _execute_one(self, project_id: str, q: SearchQuery) -> list:
        branch = next((b for b in self.repos.branches.all(project_id) if b.id == q.branch), None)
        route = route_for(branch.category.value if branch else "GENERIC",
                          branch.source_preferences if branch else None)
        results = []
        for prov in route.providers:
            # "documentation" / "government" / "forum" are web-search refinements
            target = "web" if prov in ("documentation", "government", "company") else prov
            hits = self._cached_search(target, q.text)
            for h in hits:
                h.metadata.setdefault("via_provider", prov)
            results.extend(hits)
        return results

    def _register_result(self, project_id: str, query_id: str, hit) -> Source | None:
        if not hit.url.startswith(("http://", "https://")):
            return None
        canon = url_canonicalize(hit.url)
        if not canon or "duckduckgo.com" in canon:
            return None
        existing = self.repos.sources.find_by_canonical_url(project_id, canon)
        if existing:
            if query_id not in existing.query_ids:
                existing.query_ids.append(query_id)
                self.repos.sources.save(existing)
            return None  # URL dedup at discovery time
        stype, tier = classify_source(hit.url)
        from datetime import datetime, timezone
        src = Source(
            project_id=project_id,
            url=hit.url, canonical_url=canon, title=hit.title[:300],
            domain=canon.split("/")[0] if "/" in canon else canon,
            source_type=stype, source_tier=tier,
            publication_date=hit.published_date,
            retrieval_date=datetime.now(timezone.utc).isoformat(),
            content_status=ContentStatus.DISCOVERED.value,
            doi=str(hit.metadata.get("doi") or ""),
            citation_count=hit.metadata.get("cited_by_count"),
            publisher=str(hit.metadata.get("venue") or "")[:200],
            author=", ".join(hit.metadata.get("authors", [])[:4]),
            query_ids=[query_id],
        )
        sr = SearchResult(project_id=project_id, query_id=query_id, url=hit.url,
                          canonical_url=canon, title=hit.title[:300],
                          snippet=hit.snippet[:1000], provider=str(hit.metadata.get("provider", "web")),
                          published_date=hit.published_date, metadata=dict(hit.metadata))
        sr.ensure_id()
        self.repos.search_results.save(sr)
        src.ensure_id()
        self.repos.sources.save(src)
        return src
