"""Hybrid retrieval over the research archive (spec #44, #47, #71).

Pipeline: query analysis -> keyword (FTS5) + semantic (vectors) + metadata
filters -> candidate merge -> cheap rerank -> evidence context.

Cheap scoring first; the strong model is reserved for answer generation only.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from research_engine.core.config import AppConfig
from research_engine.models.enums import EvidenceStatus
from research_engine.providers.embeddings.base import EmbeddingProvider
from research_engine.storage.database import Database
from research_engine.storage.repositories import Repositories
from research_engine.storage.vector_store import VectorStore

log = logging.getLogger(__name__)


@dataclass
class RetrievedItem:
    entity_id: str
    score: float
    components: dict = field(default_factory=dict)


@dataclass
class RetrievalResult:
    query: str
    items: list[RetrievedItem] = field(default_factory=list)
    used_semantic: bool = False


class HybridRetriever:
    def __init__(self, cfg: AppConfig, repos: Repositories,
                 embeddings: EmbeddingProvider | None = None):
        self.cfg = cfg
        self.repos = repos
        self.embeddings = embeddings
        if embeddings is not None:
            self.vectors: VectorStore | None = VectorStore(repos.db,
                                                           model_name=embeddings.name)
        else:
            self.vectors = None

    # ------------------------------------------------------------------ indexing
    def index_project(self, project_id: str) -> int:
        """Index accepted evidence claims+quotes. Returns count indexed."""
        if self.vectors is None or self.embeddings is None:
            return 0
        n = 0
        for ev in self.repos.evidence.all(project_id):
            if ev.status == EvidenceStatus.REJECTED:
                continue
            vec = self.embeddings.embed(f"{ev.claim_text} {ev.quote[:500]}")
            self.vectors.upsert(project_id, ev.id, "evidence", vec)
            n += 1
        return n

    # ------------------------------------------------------------------ retrieval
    YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

    def retrieve(self, project_id: str, question: str, top_k: int = 12,
                 kind: str = "", after_year: int | None = None) -> RetrievalResult:
        result = RetrievalResult(query=question)

        # 1. keyword candidates via FTS5
        fts_terms = " OR ".join(t for t in re.findall(r"[a-zA-Z0-9]{3,}", question))[:400]
        kw_ids: list[str] = []
        if fts_terms:
            try:
                kw_ids = self.repos.db.fts_search(project_id, fts_terms, limit=top_k * 2)
            except Exception:
                kw_ids = []

        # 2. semantic candidates (optional)
        sem_scores: dict[str, float] = {}
        if self.vectors is not None and self.embeddings is not None:
            try:
                qvec = self.embeddings.embed(question)
                for eid, sim in self.vectors.search(project_id, qvec, limit=top_k * 2):
                    sem_scores[eid] = sim
                result.used_semantic = True
            except Exception as exc:
                log.warning("semantic retrieval failed; keyword-only: %s", exc)

        # 3. merge + metadata + rerank (cheap deterministic scoring)
        candidates = set(kw_ids) | set(sem_scores)
        all_ev = {e.id: e for e in self.repos.evidence.all(project_id)
                  if e.status != EvidenceStatus.REJECTED}
        tier_w = {1: 1.0, 2: 0.85, 3: 0.6, 4: 0.4, 5: 0.25}
        for eid in candidates:
            ev = all_ev.get(eid)
            if ev is None:
                continue
            if after_year:
                try:
                    if int(str(ev.published_date)[:4]) < after_year:
                        continue
                except (ValueError, TypeError):
                    pass
            kw_component = 1.0 if eid in kw_ids else 0.0
            sem_component = sem_scores.get(eid, 0.0)
            tier_component = tier_w.get(ev.source_tier, 0.25)
            score = (0.45 * kw_component + 0.35 * sem_component
                     + 0.20 * tier_component * ev.confidence)
            if score <= 0.01 and eid in sem_scores:
                score = 0.05 * sem_scores[eid]
            result.items.append(RetrievedItem(
                entity_id=eid, score=round(score, 4),
                components={"kw": kw_component, "sem": round(sem_component, 3),
                            "tier": tier_component}))

        result.items.sort(key=lambda i: -i.score)
        result.items = result.items[:top_k]
        return result

    def context_assembly(self, result: RetrievalResult, max_chars: int = 6000) -> tuple[str, list]:
        """Deduped, ranked context with citation IDs preserved (spec #72)."""
        seen_claims: set[str] = set()
        lines: list[str] = []
        used: list = []
        budget = max_chars
        for item in result.items:
            ev = self.repos.evidence.get(item.entity_id)
            if ev is None:
                continue
            key = ev.claim_text.lower()[:80]
            if key in seen_claims:
                continue
            block = (f"[{ev.id}] ({ev.source_title[:60]}, {ev.published_date or 'n.d.'}, "
                     f"tier {ev.source_tier}) {ev.claim_text}\n"
                     f"    quote: \"{ev.quote[:300]}\"")
            if len(block) > budget:
                break
            lines.append(block)
            used.append(ev)
            seen_claims.add(key)
            budget -= len(block)
        return "\n".join(lines), used


def build_retriever(cfg: AppConfig, repos: Repositories) -> HybridRetriever:
    """Embedding provider from config; falls back to hashing (always available)."""
    from research_engine.providers.embeddings.base import (
        HashingEmbeddingProvider, OllamaEmbeddingProvider,
        OpenAICompatibleEmbeddingProvider)
    emb_cfg = getattr(cfg, "embeddings", None)
    provider_name = getattr(emb_cfg, "provider", "hashing") if emb_cfg else "hashing"
    emb: EmbeddingProvider
    if provider_name == "ollama":
        cand = OllamaEmbeddingProvider(model=getattr(emb_cfg, "model", "nomic-embed-text"),
                                       base_url=getattr(emb_cfg, "base_url", "") or
                                       "http://localhost:11434")
        emb = cand if cand.is_available() else HashingEmbeddingProvider()
    elif provider_name == "openai_compatible":
        cand = OpenAICompatibleEmbeddingProvider(
            model=getattr(emb_cfg, "model", ""), base_url=getattr(emb_cfg, "base_url", ""))
        emb = cand if cand.is_available() else HashingEmbeddingProvider()
    else:
        emb = HashingEmbeddingProvider()
    return HybridRetriever(cfg, repos, emb)
