"""Unified research action space (§50) and stopping policy v2 (§49).

The stopping policy answers: "is more web research likely to materially
improve confidence?" — and when it isn't, names the highest-information
next action (often RUN_EXPERIMENT for customer-behavior uncertainty).
Deterministic, store-derived, no LLM.
"""
from __future__ import annotations

from enum import Enum


class ResearchAction(str, Enum):
    SEARCH_WEB = "SEARCH_WEB"
    SEARCH_PAPERS = "SEARCH_PAPERS"
    FETCH_PRIMARY_SOURCE = "FETCH_PRIMARY_SOURCE"
    RUN_SPECIALIST = "RUN_SPECIALIST"
    RUN_CROSS_DOMAIN_ANALYSIS = "RUN_CROSS_DOMAIN_ANALYSIS"
    VERIFY_CLAIM = "VERIFY_CLAIM"
    SEARCH_COUNTEREVIDENCE = "SEARCH_COUNTEREVIDENCE"
    DESIGN_EXPERIMENT = "DESIGN_EXPERIMENT"
    REQUEST_USER_INPUT = "REQUEST_USER_INPUT"
    RUN_EXPERIMENT = "RUN_EXPERIMENT"
    SYNTHESIZE = "SYNTHESIZE"
    STOP = "STOP"


# Gap categories whose resolution requires real-world evidence, not more
# web pages (startup discipline: cheapest real-world test wins).
_EXPERIMENT_RESOLVABLE = (
    "customer behavior", "customers actually", "willingness to pay",
    "usability", "adoption", "pricing sensitivity", "real-world test",
    "pilot", "landing page",
)

_PRIMARY_NEEDED = ("primary", "official", "regulatory", "patent", "filing")


def recommend_next_action(orch, pid: str) -> dict:
    """Store-derived next-action recommendation (§49/§50).

    Priority order mirrors research integrity rules:
    unresolved contradictions → counterevidence search;
    weak-source claims → primary sources;
    experiment-resolvable uncertainty → DESIGN/RUN EXPERIMENT;
    open important gaps → targeted search;
    otherwise → synthesize/stop.
    """
    gaps = orch.repos.gaps.all(pid)
    open_gaps = [g for g in gaps if not g.resolved]
    important = [g for g in open_gaps if float(g.importance or 0) >= 0.5]
    contradictions = [c for c in orch.repos.contradictions.all(pid)
                      if not getattr(c, "resolved", False)]
    claims = orch.repos.claims.all(pid)
    weak_claims = [c for c in claims if c.supported_by and all(
        int(getattr(e, "source_tier", 5)) >= 4
        for e in (orch.repos.evidence.get(eid) for eid in c.supported_by)
        if e is not None)]

    def gap_text(g) -> str:
        t = f"{g.description} {g.evidence_needed}".lower()
        return t

    exp_gaps = [g for g in important
                if any(k in gap_text(g) for k in _EXPERIMENT_RESOLVABLE)]
    primary_gaps = [g for g in important
                    if any(k in gap_text(g) for k in _PRIMARY_NEEDED)]

    if contradictions:
        action, why = ResearchAction.SEARCH_COUNTEREVIDENCE.value, (
            f"{len(contradictions)} unresolved contradictions; "
            "methodology-level counterevidence search first")
    elif weak_claims:
        action, why = ResearchAction.FETCH_PRIMARY_SOURCE.value, (
            f"{len(weak_claims)} claims rest only on tier>=4 sources")
    elif exp_gaps:
        action, why = ResearchAction.DESIGN_EXPERIMENT.value, (
            f"{len(exp_gaps)} important uncertainties are "
            "experiment-resolvable; more web research will not settle them")
    elif primary_gaps:
        action, why = ResearchAction.SEARCH_PAPERS.value, (
            f"{len(primary_gaps)} gaps explicitly need primary sources")
    elif important:
        top = max(important, key=lambda g: g.importance)
        action, why = ResearchAction.RUN_SPECIALIST.value, (
            f"{len(important)} important open gaps; top: "
            f"{top.description[:80]}")
    elif open_gaps:
        action, why = ResearchAction.SYNTHESIZE.value, (
            f"only {len(open_gaps)} low-importance gaps remain")
    else:
        action, why = ResearchAction.STOP.value, (
            "no open gaps; diminishing returns from further retrieval")

    return {
        "action": action,
        "rationale": why,
        "open_important_gaps": len(important),
        "unresolved_contradictions": len(contradictions),
        "weak_source_claims": len(weak_claims),
        "experiment_resolvable_gaps": len(exp_gaps),
    }
