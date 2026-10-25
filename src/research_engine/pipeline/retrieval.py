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
from research_engine.models.research import (RESULTS_COUNT_DISTINCT_URLS,
                                            SearchQuery, SearchResult, Source)
from research_engine.pipeline.routing import ProviderRegistry, classify_source, route_for
from research_engine.storage.cache import KVCache, cache_key
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)


class RetrievalWorker:
    def __init__(self, cfg: AppConfig, repos: Repositories,
                 registry: ProviderRegistry, search_cache: KVCache | None = None):
        from research_engine.platform.resilience import FailoverExecutor
        self.cfg = cfg
        self.repos = repos
        self.registry = registry
        self.failover = FailoverExecutor()
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
                    hits, errors, outcomes, dropped_legs = fut.result()
                except Exception as exc:  # isolation: one query failure never kills the loop
                    log.warning("query %s failed: %s", q.id, exc)
                    hits, errors = [], [f"{type(exc).__name__}: {exc}"]
                    outcomes, dropped_legs = [], []
                q.executed = True
                # Decision: results_count counts DISTINCT canonical http(s)
                # URLs, not raw hits.
                # Why: two legs can surface the same document (a paper on
                # arxiv and the same paper on a preprint server), and a raw
                # hit count overstates what was actually found. The distinct
                # count is what a reader sees in the report.
                # Constraint: a hit whose URL is not http(s) is NOT counted -
                # `_register_result` skips exactly those hits, so they would
                # never become a source. The count therefore matches the
                # sources this query actually registered.
                # Constraint: the MEANING of the number is versioned by
                # `results_count_schema_version` (2 = distinct canonical
                # http(s) URLs, 1 = the legacy raw hit count), because a row
                # written by an older engine still carries the old meaning.
                q.results_count = len({url_canonicalize(h.url) for h in hits
                                       if h.url.startswith(("http://", "https://"))})
                q.results_count_schema_version = RESULTS_COUNT_DISTINCT_URLS
                q.leg_outcomes = outcomes
                # Decision: the names the route dropped are persisted with the
                # query.
                # Why: a planner that asked for a source we do not have (say
                # "github") must leave a trace, otherwise the branch looks
                # like it was served as asked.
                q.dropped_legs = dropped_legs
                if errors:
                    # Decision: a failed retrieval is recorded on the query, not
                    # flattened into an empty result.
                    # Why: "the provider failed" and "the provider found
                    # nothing" must be distinguishable (INV-012), otherwise a
                    # total search outage is reported as CONVERGED research.
                    # Constraint: `failed` is a JSON-only field (like
                    # `results_count`); it is counted in Python, not SQL.
                    q.failed = True
                    q.failure_reason = "; ".join(errors)[:500]
                for hit in hits:
                    src = self._register_result(project_id, q.id, hit)
                    if src is not None:
                        new_sources[src.canonical_url] = src
                        q.useful_results += 0  # updated later by evidence worker feedback
                self.repos.queries.save(q)
        return to_run, list(new_sources.values())

    def _cached_search(self, provider_name: str, query_text: str) -> tuple[list, str]:
        """Return (hits, error). `error` is non-empty iff the provider FAILED.

        Three cases that used to be indistinguishable, all returning []:
        a cache hit, a provider that was never configured, and a provider
        that failed. Only the third is a failure.
        """
        key = cache_key(provider_name, query_text)
        cached = self.search_cache.get(key)
        if cached is not None:
            from research_engine.providers.search.base import RawSearchHit
            return [RawSearchHit(**h) for h in cached], ""
        provider = self.registry.get_any(provider_name)
        if provider is None:
            # Not a failure: the provider was never configured (offline mode,
            # or a route leg with no provider). Counting this as a failure
            # would report an intentional offline run as a provider outage.
            return [], ""
        try:
            hits = provider.search(query_text, max_results=self.cfg.search.results_per_query)
            self.failover.breaker_for(provider_name).record_success()
        except Exception as exc:
            # The provider contract says raise on failure; catch broadly
            # anyway so a third-party provider that violates it is still
            # recorded rather than silently returning nothing.
            self.failover.breaker_for(provider_name).record_failure()
            log.warning("provider %s failed: %s", provider_name, exc)
            return [], f"{provider_name}: {type(exc).__name__}: {exc}"
        self.search_cache.put(
            key, [{"url": h.url, "title": h.title, "snippet": h.snippet,
                   "published_date": h.published_date, "metadata": h.metadata} for h in hits],
            ttl_hours=self.cfg.search.cache_ttl_hours)
        return hits, ""

    def _execute_one(self, project_id: str, q: SearchQuery) -> tuple[list, list[str], list[dict], list[str]]:
        """Run one query's route.

        Returns (hits, errors, leg_outcomes, dropped_legs):
        - `errors` holds the providers that FAILED (never the ones that were
          never configured - INV-012);
        - `leg_outcomes` holds one entry per route leg, so a leg that
          resolved to nothing is visible;
        - `dropped_legs` holds the names the route did not contain.
        """
        branch = next((b for b in self.repos.branches.all(project_id) if b.id == q.branch), None)
        route = route_for(branch.category if branch else "GENERIC",
                          branch.source_preferences if branch else None)
        results = []
        errors: list[str] = []
        outcomes: list[dict] = []
        for leg in route.legs:
            # Each leg searches its own query text, so two legs on the same
            # provider return different hits instead of the same cached set.
            query_text = f"{q.text}{leg.query_suffix}"
            # Decision: the registry is consulted BEFORE the cache.
            # Why: the search cache is a GLOBAL, cross-project cache that
            #   outlives the run that filled it, so a cached hit set can
            #   survive a configuration change. Serving those hits for a
            #   provider the operator has since disabled would report
            #   network-derived results for an explicitly offline install -
            #   the same defect class as the watcher building its own
            #   provider. A leg whose provider is not registered is
            #   `unconfigured`, whatever the cache happens to hold.
            # Constraint: the cache is still consulted for a REGISTERED
            #   provider, so a configured provider keeps its cached hits and
            #   the cache still saves the network call.
            if self.registry.get_any(leg.provider) is None:
                # Not a failure: this provider was never configured (offline
                # mode, or an optional provider the operator did not enable).
                # It is still reported, so a leg that can never resolve is
                # visible instead of silently contributing zero results.
                # Decision: the invariant "an unconfigured provider is not a
                # failure" (INV-012) holds for the whole class; the leg is
                # recorded so the gap is visible, not so it can be counted as
                # an outage.
                # Constraint: an OPTIONAL leg that is not registered is a
                # declared state (`optional_unconfigured`), a REQUIRED one is
                # a configuration gap (`unconfigured`). The two are different
                # facts about the installation, so they get different names.
                status = "optional_unconfigured" if leg.optional else "unconfigured"
                outcomes.append({"leg": leg.name, "provider": leg.provider,
                                 "status": status, "hits": 0,
                                 "error": ""})
                continue
            hits, err = self._cached_search(leg.provider, query_text)
            if err:
                errors.append(err)
                outcomes.append({"leg": leg.name, "provider": leg.provider,
                                 "status": "failed", "hits": 0,
                                 "error": err[:200]})
                continue
            for h in hits:
                # Decision: the hit records the LEG it came from, not the
                # provider.
                # Why: two legs can share one provider ("web" and
                # "documentation"), so the provider name cannot attribute the
                # hit - the leg name can. The provider is already on the
                # `SearchResult` row (`provider`).
                # Constraint: the metadata key is named after the value, so a
                # reader never has to guess which of the two it holds.
                h.metadata.setdefault("via_leg", leg.name)
            results.extend(hits)
            outcomes.append({"leg": leg.name, "provider": leg.provider,
                             "status": "hits", "hits": len(hits), "error": ""})
        return results, errors, outcomes, list(route.dropped_legs)

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
