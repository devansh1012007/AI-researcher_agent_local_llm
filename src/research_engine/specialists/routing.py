"""Specialist routing (Phase 5 §6–§7, §18) — HYBRID.

Deterministic domain-signal rules SELECT; an optional schema-validated LLM
step may only ANNOTATE or VETO existing selections. The rules' output is the
floor: when no LLM is available (offline/local-first default), rules stand
alone. No learned routing in this phase (§18) — performance data collection
only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

# Deterministic, transparent vocabulary per specialist domain. Extensible:
# specialists may register extra keywords via descriptor.research_policies
# ("routing_keywords").
DOMAIN_SIGNALS: dict[str, list[str]] = {
    "literature": [
        "paper", "papers", "literature", "prior work", "novelty",
        "state of the art", "sota", "benchmark", "method comparison",
        "research gap", "study", "academic", "survey",
    ],
    "technology": [
        "feasib", "technical", "engineering", "hardware", "integration",
        "deployment", "complexity", "constraint", "prototype", "latency",
        "compute requirement", "open-source alternative",
    ],
    "startup": [
        "market", "customer", "pain", "competitor landscape", "pricing",
        "willingness to pay", "wtp", "opportunity", "segment", "why now",
        "go-to-market", "validation",
    ],
    "competitive": [
        "competitor", "positioning", "funding", "customer review",
        "feature comparison", "market share", "product evolution",
    ],
    "foresight": [
        "trend", "emerging", "disruption", "regulation change",
        "platform shift", "cost curve", "adoption signal", "new release",
        "threatened by",
    ],
}


@dataclass
class Selection:
    specialist_id: str
    reason: str
    score: float = 0.0
    version: str | None = None
    annotations: list[str] = field(default_factory=list)


class RouteVeto(BaseModel):
    id: str
    reason: str = ""


class RouteAnnotation(BaseModel):
    """LLM output contract: may ONLY veto/annotate rule selections."""
    veto: list[RouteVeto] = []
    notes: list[RouteVeto] = []   # reuse shape; advisory text


def route(question: str, subquestions: list[str] | None = None,
          llm=None, max_specialists: int = 5) -> list[Selection]:
    """Hybrid selection. Rules first; `llm` (optional) may veto/annotate."""
    text = " ".join([question or ""] + list(subquestions or [])).lower()
    selections: list[Selection] = []
    for sid, kws in DOMAIN_SIGNALS.items():
        hits = sorted({k for k in kws if k in text})
        if hits:
            selections.append(Selection(
                specialist_id=sid,
                reason="matched domain signals: " + ", ".join(hits[:4]),
                score=float(len(hits))))
    selections.sort(key=lambda s: -s.score)

    vetted: list[Selection] = []
    if llm is not None and selections:
        vetted = _apply_llm_annotation(selections, question, llm)
    else:
        vetted = selections
    return vetted[:max_specialists]


def _apply_llm_annotation(selections: list[Selection], question: str,
                          llm) -> list[Selection]:
    """Fail-open: any LLM problem leaves rule selections untouched."""
    try:
        out = llm.structured(
            "You validate specialist routing for a research task. Only "
            "veto selections that are clearly irrelevant.",
            f"question: {question}\nselected: "
            f"{[s.specialist_id for s in selections]}",
            RouteAnnotation)
    except Exception:
        return [s for s in selections if s.annotations.append(
            "llm_annotate_error") or True]
    if out is None:
        for s in selections:
            s.annotations.append("llm_annotate_unavailable")
        return selections
    vetoed = {v.id: v.reason for v in (out.veto or [])}
    notes = {n.id: n.reason for n in (out.notes or [])}
    kept = []
    for s in selections:
        if s.specialist_id in vetoed:
            continue
        if s.specialist_id in notes:
            s.annotations.append(f"llm: {notes[s.specialist_id]}"[:120])
        kept.append(s)
    return kept
