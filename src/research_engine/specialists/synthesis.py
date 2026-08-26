"""Cross-specialist synthesis (Phase 5 §39–§41, §63–§65).

READ-ONLY composition over persisted project state: connections,
opportunities, gaps, contradictions, per-domain confidence. Domain
boundaries are preserved (§40): technical feasibility never collapses into
market demand; each dimension keeps its own confidence (§63).
"""
from __future__ import annotations


def synthesize(orch) -> dict:
    from research_engine.specialists.cross_domain import CrossDomainRepos
    pid = orch.project.id
    repos = CrossDomainRepos(orch.db).connections
    connections = repos.all(pid)

    opps = list(orch.repos.opportunities.all(pid))
    gaps = orch.repos.gaps.all(pid)
    contradictions = orch.repos.contradictions.all(pid)

    # ---- §64 decision matrix: per-dimension confidence -----------------
    dims: dict[str, list[float]] = {
        "technical": [], "market": [], "customer": [],
        "competition": [], "distribution": [], "regulatory": [],
    }
    for c in connections:
        pair = {c.source_domain, c.target_domain}
        if "technology" in pair:
            dims["technical"].append(c.confidence)
        if "startup" in pair or "market" in pair:
            dims["market"].append(c.confidence)
    for o in opps:
        sb = getattr(o, "score_breakdown", {}) or {}
        factors = sb.get("factors", {}) or {}
        mapping = {
            "pain_severity": "customer", "pain_frequency": "customer",
            "wtp_evidence": "customer", "economic_value": "market",
            "market_size": "market", "competition_weakness":
                "competition",
            "distribution": "distribution", "technical_feasibility":
                "technical",
        }
        for factor, dim in mapping.items():
            if factor in factors:
                dims[dim].append(float(factors[factor]))

    matrix = {}
    for dim, vals in dims.items():
        matrix[dim] = {
            "confidence": round(sum(vals) / len(vals), 3) if vals else None,
            "n_signals": len(vals),
            "label": (_label(sum(vals) / len(vals)) if vals else "UNKNOWN"),
        }

    # ---- §65 weakest high-impact dimension queue -----------------------
    queue = sorted(
        ((d, v["confidence"]) for d, v in matrix.items()
         if v["confidence"] is not None),
        key=lambda kv: kv[1])
    next_actions = [{"dimension": d, "confidence": c,
                     "action": f"research {d} evidence to raise "
                               "decision confidence"}
                    for d, c in queue[:2]]

    validated = [c for c in connections if c.status == "VALIDATED"]
    contested = [c for c in connections if c.status == "CONTESTED"]

    integrated = []
    for o in opps[:3]:
        sb = getattr(o, "score_breakdown", {}) or {}
        integrated.append({
            "kind": "opportunity",
            "id": o.id,
            "problem": o.problem[:140],
            "total": sb.get("total"),
            "evidence_ids": list(getattr(o, "evidence_ids", [])),
        })
    for c in validated:
        integrated.append({
            "kind": "connection",
            "id": c.id,
            "relationship": c.relationship,
            "source_entity": c.source_entity,
            "target_entity": c.target_entity,
            "confidence": c.confidence,
            "evidence_ids": list(c.evidence_ids),
        })

    cross_contras = [
        {"id": k.id,
         "specialist_a": k.specialist_a,
         "specialist_b": k.specialist_b,
         "statement_a": k.statement_a[:140],
         "statement_b": k.statement_b[:140],
         "domain_difference": k.domain_difference,
         "status": "OPEN" if not k.resolved else "RESOLVED"}
        for k in contradictions
        if str(k.conflict_type).startswith("CROSS_DOMAIN")]

    return {
        "project_id": pid,
        "decision_matrix": matrix,
        "weakest_dimensions_queue": next_actions,
        "integrated_findings": integrated,
        "cross_domain_contradictions": cross_contras,
        "connections_summary": {
            "proposed": sum(1 for c in connections
                            if c.status == "PROPOSED"),
            "validated": len(validated),
            "contested": len(contested),
        },
        "open_gaps_high_importance": [
            {"id": g.id, "description": g.description}
            for g in gaps if getattr(g, "importance", 0) >= 4],
        "note": "read-only synthesis over persisted state (INV-004)",
    }


def _label(v: float) -> str:
    if v >= 0.66:
        return "HIGH"
    if v >= 0.33:
        return "MEDIUM"
    return "LOW"
