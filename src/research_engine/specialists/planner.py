"""Cross-specialist composition planner (Phase 5 §8, §29, §66, §67).

Builds a sequential stage plan from routed selections. Local-first rule
(§82): parallel retrieval is fine inside a specialist; heavy reasoning
stages run sequentially. Cycle protection (§67) = invocation-history guard:
a specialist re-invoked for the same project must show research gain (new
evidence since its previous run) or the runner skips it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MAX_SPECIALISTS_PER_PROJECT = 5
MIN_GAIN_FOR_REINVOCATION = 1  # new evidence items required


@dataclass
class Stage:
    index: int
    specialist_id: str
    mode: str
    objective: str
    version: str | None = None
    reason: str = ""
    skipped_reason: str = ""


WORKFLOW_TEMPLATES: dict[str, list[str]] = {
    # flagship (§60/§79): gap → feasibility → market → validation
    "RESEARCH_GAP_TO_STARTUP": ["literature", "technology", "startup"],
    # §28: which opportunities are threatened by emerging tech
    "TECH_RISK": ["startup", "competitive", "foresight"],
    "LITERATURE_ONLY": ["literature"],
    "TECHNOLOGY_ONLY": ["technology"],
}


def default_template_for_mode(mode: str) -> str | None:
    m = (mode or "").lower()
    if "startup" in m:
        return "RESEARCH_GAP_TO_STARTUP"
    if any(k in m for k in ("academic", "research", "literature")):
        return "LITERATURE_ONLY"
    if "feasib" in m or "technical" in m:
        return "TECHNOLOGY_ONLY"
    return None


def build_plan(selections, question: str,
               template: str | None = None) -> list[Stage]:
    """Order selections by workflow template when one applies; otherwise
    keep routing-score order. Enforces §66 limits."""
    order: list[str] = []
    tname = template or _guess_template(question, selections)
    if tname and tname in WORKFLOW_TEMPLATES:
        wanted = [s for s in WORKFLOW_TEMPLATES[tname]
                  if s in {x.specialist_id for x in selections}]
        extras = [x.specialist_id for x in selections
                  if x.specialist_id not in wanted]
        order = wanted + extras[:max(0, MAX_SPECIALISTS_PER_PROJECT - len(wanted))]
    else:
        order = [s.specialist_id for s in selections]
    order = order[:MAX_SPECIALISTS_PER_PROJECT]

    sel_by_id = {}
    for s in selections:
        sel_by_id.setdefault(s.specialist_id, s)

    stages: list[Stage] = []
    for i, sid in enumerate(order):
        s = sel_by_id[sid]
        stages.append(Stage(index=i, specialist_id=sid,
                            mode=_mode_for(sid), objective=question,
                            reason=s.reason))
    return stages


def _mode_for(sid: str) -> str:
    return {
        "literature": "LITERATURE_REVIEW",
        "technology": "FEASIBILITY",
        "startup": "OPPORTUNITY_DISCOVERY",
        "competitive": "COMPETITIVE_ANALYSIS",
        "foresight": "TREND_SCAN",
    }.get(sid, "ANALYZE")


def _guess_template(question: str, selections) -> str | None:
    q = (question or "").lower()
    ids = {s.specialist_id for s in selections}
    if {"literature", "technology", "startup"} & ids and \
            any(k in q for k in ("gap", "opportunity")):
        return "RESEARCH_GAP_TO_STARTUP"
    if {"foresight", "competitive"} & ids and "threat" in q:
        return "TECH_RISK"
    return None


def gain_guard(specialist_id: str, evidence_count_now: int,
               prior_invocations: list[dict]) -> str:
    """§67: return '' when invocation may proceed, else the skip reason."""
    prior = [p for p in prior_invocations
             if p.get("specialist_id") == specialist_id]
    if not prior:
        return ""
    last = max(prior, key=lambda p: p.get("created_at", ""))
    delta = evidence_count_now - int(last.get("evidence_count", 0))
    if delta < MIN_GAIN_FOR_REINVOCATION:
        return (f"cycle-guard: no research gain since last "
                f"{specialist_id} run (+{delta} evidence)")
    return ""
