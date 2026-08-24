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
        for name in ("openalex", "arxiv", "semantic_scholar"):
            prov = self.registry.get_any(name)
            if prov is None:
                continue
            try:
                hits.extend(prov.search(query, max_results=max_hits))
            except Exception as exc:
                log.warning("novelty search %s failed: %s", name, exc)
        if not hits:
            return {"novelty_status": "uncertain",
                    "reason": "no prior-art search results available; cannot establish novelty",
                    "closest": [], "query": query}

        # similarity of hypothesis text vs titles+abstracts
        idx = TfidfIndex()
        docs = [_tokens(h.title + " " + h.snippet[:600]) for h in hits]
        idx.fit(docs)
        hvec = idx.vector(_tokens(statement))
        scored = sorted(
            ((TfidfIndex.cosine(hvec, d), h) for h, d in zip(hits, docs)),
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
        return {
            "novelty_status": status,
            "reason": reason,
            "top_similarity": round(top_sim, 3),
            "query": query,
            "closest": [{"title": h.title[:100], "url": h.url, "year": h.published_date}
                        for _, h in scored[:3]],
        }
