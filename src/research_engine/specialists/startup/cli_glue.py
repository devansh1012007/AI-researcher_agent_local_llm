"""CLI glue for the startup specialist (P0-11/P0-12).

Thin adapters so CLI commands consume the canonical specialist service
without importing legacy engines. Read-only over stored state unless a
service mode is explicitly invoked.
"""
from __future__ import annotations


def market_map_view(svc, project_id: str) -> dict:
    """Read-only market-map view: extraction counts + stored opportunities."""
    repos, srepos, rrepos, graph = svc._repos_for(svc._orch(project_id))

    from research_engine.specialists.startup.customers import CustomerAnalyzer
    pains = CustomerAnalyzer(repos, None, srepos).analyze_pains(project_id)
    competitors = srepos.competitor_profiles.all(project_id)
    pricing = srepos.pricing_plans.all(project_id)
    signals = graph.entities(project_id, "market_signal")
    opportunities = sorted(
        repos.opportunities.all(project_id),
        key=lambda o: -((o.score_breakdown or {}).get("total", 0)))[:10]
    return {
        "extraction_counts": {
            "pains": len(pains),
            "competitors": len(competitors),
            "pricing_observations": len(pricing),
            "signals": len(signals),
        },
        "opportunities": [
            {"opportunity_id": o.id,
             "problem": o.problem[:160],
             "total_score": (o.score_breakdown or {}).get("total", 0),
             "priority": (o.score_breakdown or {}).get("gate", {}).get("priority",
                                                                      "")}
            for o in opportunities],
        "open_questions": [g.description[:140] for g in
                           sorted(repos.gaps.all(project_id),
                                  key=lambda g: -g.importance)[:8]
                           if not g.resolved],
    }


def opportunity_portfolio(svc, project_id: str) -> list[dict]:
    """Canonical discovery mode output (replaces legacy discover+score)."""
    result = svc.run_mode(project_id, "OPPORTUNITY_DISCOVERY")
    return result.get("opportunities", [])


def ensure_business_hypotheses(svc, project_id: str) -> int:
    """Idempotent hypothesis chain for discovered opportunities."""
    orch = svc._orch(project_id)
    repos, srepos, rrepos, graph = svc._repos_for(orch)
    provider = getattr(getattr(orch, "router", None), "reasoning", None)
    n = 0
    for t in svc.run_mode(project_id, "OPPORTUNITY_DISCOVERY").get(
            "opportunities", [])[:3]:
        opp = repos.opportunities.get(t["opportunity_id"])
        if opp is not None:
            n += svc._ensure_business_hypotheses(repos, rrepos, provider,
                                                 project_id, opp)
    return n
