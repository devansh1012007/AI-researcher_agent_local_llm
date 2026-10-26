"""Novelty verification: has this 'new' hypothesis already been explored?

Searches configured academic providers for prior art on the hypothesis statement,
extracts closest known work, and outputs a graded novelty status. Never claims
novelty with certainty beyond what search can establish (spec #104).
"""
from __future__ import annotations

import logging
import re

from research_engine.intelligence.literature import TfidfIndex, _tokens
from research_engine.providers.search.base import RawSearchHit

log = logging.getLogger(__name__)


def _query_from_hypothesis(statement: str) -> str:
    words = [w for w in re.findall(r"[a-zA-Z]{4,}", statement)
             if w.lower() not in {"because", "which", "there", "these", "those",
                                  "causes", "leads", "under", "when"}]
    return " ".join(words[:8])


class NoveltyVerifier:
    def __init__(self, registry):
        """registry: pipeline.routing.ProviderRegistry-like (get_any(name))."""
        self.registry = registry

    def verify(self, statement: str, max_hits: int = 10) -> dict:
        query = _query_from_hypothesis(statement)
        hits: list[RawSearchHit] = []
        # Decision: an unconfigured provider is reported, not skipped.
        # Why: the old code did `continue` on a missing provider, so a run
        # with no academic providers configured produced the same result as a
        # run that searched and found nothing - "uncertain" for two very
        # different reasons, with no way to tell them apart.
        # Constraint: the uncertainty verdict itself is unchanged; only the
        # reason now names which providers were unavailable.
        unconfigured: list[str] = []
        failures: list[str] = []
        for name in ("openalex", "arxiv", "semantic_scholar"):
            prov = self.registry.get_any(name)
            if prov is None:
                unconfigured.append(name)
                continue
            try:
                hits.extend(prov.search(query, max_results=max_hits))
            except Exception as exc:
                log.warning("novelty search %s failed: %s", name, exc)
                failures.append(f"{name}: {type(exc).__name__}: {exc}")
        if not hits:
            reason = "no prior-art search results available; cannot establish novelty"
            if unconfigured:
                reason += f" (providers not configured: {', '.join(unconfigured)})"
            if failures:
                reason += f" (provider failures: {'; '.join(failures)})"
            return {"novelty_status": "uncertain",
                    "reason": reason,
                    "unconfigured_providers": unconfigured,
                    "provider_failures": failures,
                    "closest": [], "query": query}

        # similarity of hypothesis text vs titles+abstracts
        idx = TfidfIndex()
        docs = [_tokens(h.title + " " + h.snippet[:600]) for h in hits]
        idx.fit(docs)
        hvec = idx.vector(_tokens(statement))
        # Decision: compare VECTORS, not token lists.
        # Why: `cosine` expects the dict form `TfidfIndex.vector` returns;
        # passing the raw token list raised AttributeError ('list' object has
        # no attribute 'get') on every call that reached a similarity
        # comparison, so this path could only ever return "uncertain".
        # Constraint: the document vectors must be built from the SAME fitted
        # index as the hypothesis vector, or the idf weights differ.
        doc_vectors = [idx.vector(d) for d in docs]
        scored = sorted(
            ((TfidfIndex.cosine(hvec, dv), h) for h, dv in zip(hits, doc_vectors)),
            key=lambda t: -t[0])
        top_sim = scored[0][0] if scored else 0.0

        if top_sim >= 0.45:
            status = "already_explored"
        elif top_sim >= 0.30:
            status = "incremental"
        elif top_sim >= 0.18:
            status = "possibly_novel"
        else:
            status = "likely_novel"
        reason = (f"closest of {len(hits)} prior works has similarity {top_sim:.2f}; "
                  "search-based estimate only")
        # Decision: the provider report is on EVERY return path, not only the
        # no-hits path.
        # Why: a run where one provider raised and another returned hits used
        # to return a verdict that named neither - the failure was invisible
        # except in the log, so a single-provider search was indistinguishable
        # from a three-provider search.
        # Constraint: the verdict itself is unchanged; only the report grows.
        if unconfigured:
            reason += f" (providers not configured: {', '.join(unconfigured)})"
        if failures:
            reason += f" (provider failures: {'; '.join(failures)})"
        return {
            "novelty_status": status,
            "reason": reason,
            "top_similarity": round(top_sim, 3),
            "query": query,
            "unconfigured_providers": unconfigured,
            "provider_failures": failures,
            "closest": [{"title": h.title[:100], "url": h.url, "year": h.published_date}
                        for _, h in scored[:3]],
        }
