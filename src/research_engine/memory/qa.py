"""Grounded Q&A over the project research archive (spec #48).

Answers ONLY from stored evidence. Returns answer + evidence citations +
confidence + unknowns. If the archive cannot support an answer, it says so -
it never fills gaps from generic model memory.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from pydantic import BaseModel

from research_engine.memory.retrieval import HybridRetriever
from research_engine.providers.llm.base import LLMProvider
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)

_INSUFFICIENT = ("The research archive does not contain sufficient evidence to "
                 "answer this question.")


class _QAOut(BaseModel):
    answer: str = ""
    evidence_ids: list[str] = []
    unknowns: list[str] = []
    insufficient: bool = False


@dataclass
class QAResponse:
    question: str
    answer: str
    evidence: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    confidence: float = 0.0
    unknowns: list[str] = field(default_factory=list)
    insufficient: bool = False


class GroundedQA:
    def __init__(self, repos: Repositories, retriever: HybridRetriever,
                 provider: LLMProvider | None):
        self.repos = repos
        self.retriever = retriever
        self.provider = provider

    def ask(self, project_id: str, question: str, top_k: int = 12) -> QAResponse:
        result = self.retriever.retrieve(project_id, question, top_k=top_k)
        context, used_ev = self.retriever.context_assembly(result)

        if not used_ev:
            return QAResponse(question=question, answer=_INSUFFICIENT,
                              insufficient=True, confidence=0.0)

        # deterministic baseline answer assembled from retrieved evidence
        det_answer = "\n".join(f"- {ev.claim_text} [{ev.id}]"
                               for ev in used_ev[:8])
        confidence = round(sum(i.score for i in result.items[:len(used_ev)])
                           / max(1, len(used_ev)), 3)

        # LLM composes a coherent answer strictly from context, when available
        llm_answer, llm_ids, unknowns, insufficient = None, [], [], False
        if self.provider is not None:
            system = (
                "You answer research questions using ONLY the provided evidence.\n"
                "Rules:\n"
                "- Cite evidence IDs like [ev_000001] for every factual statement.\n"
                "- NEVER add information absent from the evidence. Never use your own knowledge.\n"
                "- If evidence is insufficient or contradictory, say so explicitly.\n"
                '- Respond ONLY with JSON: {"answer": "markdown", "evidence_ids": [...], '
                '"unknowns": ["..."], "insufficient": false}')
            user = (f"Question: {question}\n\nEvidence:\n{context}\n\n"
                    "Answer the question from this evidence only.")
            out, errors = self.provider.structured(system, user, _QAOut)
            if out is not None and not out.insufficient and out.answer.strip():
                valid_ids = {e.id for e in used_ev}
                llm_answer = out.answer
                llm_ids = [i for i in out.evidence_ids if i in valid_ids]
                unknowns = [u[:200] for u in out.unknowns][:5]
            elif out is not None and out.insufficient:
                insufficient = True
                unknowns = [u[:200] for u in out.unknowns][:5]

        if insufficient:
            return QAResponse(question=question,
                              answer=f"{_INSUFFICIENT} Related material found: see evidence below.",
                              evidence=used_ev[:6], unknowns=unknowns,
                              confidence=round(confidence * 0.5, 3))

        sources = []
        seen = set()
        for ev in used_ev:
            src = self.repos.sources.get(ev.source_id)
            if src and src.id not in seen:
                seen.add(src.id)
                sources.append(src)

        answer_text = llm_answer or det_answer
        cited = llm_ids or [e.id for e in used_ev[:8]]
        final_ev = [e for e in used_ev if e.id in set(cited)] or used_ev[:8]
        return QAResponse(question=question, answer=answer_text,
                          evidence=final_ev, sources=sources,
                          confidence=confidence, unknowns=unknowns)

    def format_response(self, r: QAResponse) -> str:
        lines = [r.answer, "", "**Evidence:**"]
        lines += [f"- {e.id} — \"{e.quote[:120]}\" ({e.source_title[:50]})"
                  for e in r.evidence[:8]] or ["- none"]
        if r.sources:
            lines += ["", "**Sources:**"]
            lines += [f"- {s.title[:70]} — {s.url}" for s in r.sources[:6]]
        lines += ["", f"**Confidence:** {r.confidence:.2f}"]
        if r.unknowns:
            lines += ["", "**Unknowns:**"] + [f"- {u}" for u in r.unknowns]
        return "\n".join(lines)


def trace_claim(repos: Repositories, claim_id: str) -> dict:
    """Claim -> evidence -> document -> source traceability chain (spec #109)."""
    claim = repos.claims.get(claim_id)
    if claim is None:
        return {"error": f"claim not found: {claim_id}"}
    chain = {"claim": claim.model_dump(), "evidence": []}
    all_sources = {}
    for eid in claim.supported_by:
        ev = repos.evidence.get(eid)
        if ev is None:
            continue
        entry = ev.model_dump()
        doc = repos.documents.get(ev.document_id)
        entry["document_url"] = doc.url if doc else ""
        src = repos.sources.get(ev.source_id)
        if src:
            all_sources[src.id] = {"id": src.id, "title": src.title, "url": src.url,
                                   "tier": src.source_tier}
        chain["evidence"].append(entry)
    chain["sources"] = list(all_sources.values())
    chain["contradictions"] = [
        c.model_dump() for c in repos.contradictions.all(claim.project_id)
        if claim_id in (c.claim_a_id, c.claim_b_id)]
    return chain
