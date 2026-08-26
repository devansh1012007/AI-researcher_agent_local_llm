"""Specialist context assembly (Phase 5 §10).

A specialist receives a SCOPED context pack — relevant evidence summaries,
not the project database. Retrieval is keyword-scored against the question
and any incoming handoff focus; hard-capped by the invocation document
budget. Local-first: no embeddings required.
"""
from __future__ import annotations


def assemble_context_pack(orch, handoff=None, max_documents: int = 30,
                          focus_terms: list[str] | None = None) -> dict:
    pid = orch.project.id
    question = (getattr(orch.project, "question_raw", "") or "").lower()
    terms = set((focus_terms or []) + question.split())
    terms = {t.strip(".,;:!?()[]\"'") for t in terms if len(t) > 2}

    sources = {s.id: s for s in orch.repos.sources.all(pid)}
    evidence = orch.repos.evidence.all(pid)

    def score(ev) -> int:
        text = f"{ev.claim_text} {ev.quote}".lower()
        base = sum(1 for t in terms if t in text)
        if handoff and getattr(handoff, "objective", ""):
            hterms = {w for w in handoff.objective.lower().split()
                      if len(w) > 3}
            base += 2 * sum(1 for t in hterms if t in text)
        return base

    ranked = sorted(evidence, key=score, reverse=True)[:max_documents]
    if handoff and getattr(handoff, "evidence_ids", None):
        wanted = [e for e in evidence if e.id in set(handoff.evidence_ids)]
        seen = {e.id for e in ranked}
        ranked = wanted + [e for e in ranked if e.id not in seen]
        ranked = ranked[:max_documents]

    items = [{
        "id": e.id,
        "claim_text": e.claim_text,
        "quote": e.quote[:280],
        "source_tier": e.source_tier,
        "source_title": next((s.title for sid, s in sources.items()
                              if sid == e.source_id), ""),
        "support_verdict": getattr(e, "support_verdict", ""),
    } for e in ranked]

    claims = [{"id": c.id, "text": c.text, "kind": str(c.kind),
               "supported_by": list(c.supported_by)}
              for c in orch.repos.claims.all(pid)[-40:]]

    gaps = [{"id": g.id, "description": g.description,
             "importance": g.importance}
            for g in orch.repos.gaps.all(pid)]

    return {
        "question": getattr(orch.project, "question_raw", ""),
        "mode": getattr(orch.project, "mode", ""),
        "evidence": items,
        "evidence_total": len(evidence),
        "claims": claims,
        "gaps": gaps,
        "handoff": handoff.model_dump() if handoff is not None else None,
    }
