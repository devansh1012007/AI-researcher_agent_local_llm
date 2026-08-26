"""Cross-domain intelligence (Phase 5 §21–§26, §38–§41, §61–§65).

Connections between domains are PROPOSED, evidence-linked artifacts. A
connection is never valid merely because two concepts are related (§24):
confidence is COMPUTED via the canonical INV-007 aggregator over linked
evidence, and domain-specific standards (§61/§62) gate VALIDATED status.
"""
from __future__ import annotations

from research_engine.models.analysis import Connection
from research_engine.storage.reasoning_repos import _GenericRepo

# §23 taxonomy — extensible by adding constants; nothing downstream
# hard-codes membership beyond the standards below.
RESEARCH_TO_MARKET = "RESEARCH_TO_MARKET"
MARKET_TO_TECHNOLOGY = "MARKET_TO_TECHNOLOGY"
TECHNOLOGY_TO_PRODUCT = "TECHNOLOGY_TO_PRODUCT"
REGULATION_TO_MARKET = "REGULATION_TO_MARKET"
COMPETITOR_TO_RESEARCH = "COMPETITOR_TO_RESEARCH"
CUSTOMER_PAIN_TO_TECHNOLOGY = "CUSTOMER_PAIN_TO_TECHNOLOGY"
RESEARCH_GAP_TO_STARTUP = "RESEARCH_GAP_TO_STARTUP"

CONNECTION_TYPES = {
    RESEARCH_TO_MARKET, MARKET_TO_TECHNOLOGY, TECHNOLOGY_TO_PRODUCT,
    REGULATION_TO_MARKET, COMPETITOR_TO_RESEARCH,
    CUSTOMER_PAIN_TO_TECHNOLOGY, RESEARCH_GAP_TO_STARTUP,
}

# §61: a scientific breakthrough does NOT count as startup evidence alone.
RESEARCH_TO_MARKET_STANDARD = {
    "technical": 1, "customer_problem": 1, "market": 1,
}
# §62: a customer complaint does NOT establish a technical solution exists.
PROBLEM_TO_SOLUTION_STANDARD = {
    "problem": 1, "technical_feasibility": 1,
}

STANDARDS = {
    RESEARCH_TO_MARKET: RESEARCH_TO_MARKET_STANDARD,
    RESEARCH_GAP_TO_STARTUP: RESEARCH_TO_MARKET_STANDARD,
    CUSTOMER_PAIN_TO_TECHNOLOGY: PROBLEM_TO_SOLUTION_STANDARD,
}


class CrossDomainRepos:
    """Bundle for connection persistence (INV-003 natural key)."""

    class _ConnectionsRepo(_GenericRepo):
        table = "cross_connections"
        model = Connection

        def natural_key(self, c: Connection) -> dict:
            return {"source_entity": c.source_entity,
                    "target_entity": c.target_entity,
                    "relationship": c.relationship}

    def __init__(self, db):
        self.connections = self._ConnectionsRepo(db)


def compute_connection_confidence(orch, evidence_ids: list[str]) -> float:
    """INV-015/§63: confidence comes from the CANONICAL aggregator applied
    to the linked evidence — never from specialist enthusiasm."""
    from research_engine.models.evidence import Claim
    from research_engine.reasoning.evidence_quality import (
        aggregate_claim_strength)
    evs = [e for e in orch.repos.evidence.all(orch.project.id)
           if e.id in set(evidence_ids)]
    if not evs:
        return 0.0
    holder = Claim(project_id=orch.project.id, text="connection support")
    return round(aggregate_claim_strength(holder, evs).score, 3)


def propose_connection(orch, *, source_domain: str, target_domain: str,
                       source_entity: str, target_entity: str,
                       relationship: str, rationale: str,
                       evidence_ids: list[str],
                       alternative_explanations=None) -> Connection:
    if relationship not in CONNECTION_TYPES:
        raise ValueError(f"unknown connection type {relationship!r}")
    repos = CrossDomainRepos(orch.db)
    known = {e.id for e in orch.repos.evidence.all(orch.project.id)}
    linked = [e for e in evidence_ids if e in known]
    conn = Connection(
        project_id=orch.project.id,
        source_domain=source_domain, target_domain=target_domain,
        source_entity=source_entity, target_entity=target_entity,
        relationship=relationship, rationale=rationale[:500],
        alternative_explanations=list(alternative_explanations or []),
        evidence_ids=linked,
        confidence=compute_connection_confidence(orch, linked),
        status="PROPOSED",
        requirements=dict(STANDARDS.get(relationship, {})),
    )
    conn.ensure_id()
    saved = repos.connections.save_natural(conn)
    return saved


def validate_connection(orch, connection_id: str) -> dict:
    """§24/§61/§62: apply the domain standard. Fail-closed — missing any
    required evidence class keeps the connection PROPOSED (or CONTESTED
    when counter-evidence exists)."""
    repos = CrossDomainRepos(orch.db)
    conn = repos.connections.get(connection_id)
    if conn is None:
        raise ValueError(f"connection not found: {connection_id}")

    evidence = {e.id: e for e in orch.repos.evidence.all(orch.project.id)}
    classes: dict[str, int] = {}
    for eid in conn.evidence_ids:
        e = evidence.get(eid)
        if e is None:
            continue
        text = f"{e.claim_text} {e.quote}".lower()
        if any(k in text for k in ("benchmark", "method", "prototype",
                                   "feasib", "gpu", "integration")):
            classes["technical"] = classes.get("technical", 0) + 1
            classes["technical_feasibility"] = classes.get(
                "technical_feasibility", 0) + 1
        if any(k in text for k in ("complain", "pain", "frustrat",
                                   "manual", "willingness to pay")):
            classes["customer_problem"] = classes.get(
                "customer_problem", 0) + 1
            classes["problem"] = classes.get("problem", 0) + 1
        if any(k in text for k in ("market size", "pricing", "spend",
                                   "segment", "competitor")):
            classes["market"] = classes.get("market", 0) + 1

    standard = STANDARDS.get(conn.relationship, {})
    unmet = [cls for cls, need in standard.items()
             if classes.get(cls, 0) < need]

    conn.status = ("CONTESTED" if conn.alternative_explanations and unmet
                   else "VALIDATED" if not unmet else "PROPOSED")
    repos.connections.save(conn)
    return {"status": conn.status, "unmet_classes": unmet,
            "evidence_classes": classes}
