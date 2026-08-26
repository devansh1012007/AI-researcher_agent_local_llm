"""Startup specialist adapter (Phase 5 §19.2) + builtin registration.

The existing StartupResearchService remains the authoritative application
path; the adapter only translates its mode context into the standard
SpecialistOutput contract so the ecosystem can compose with it.
"""
from __future__ import annotations


def startup_invoke(rc):
    from research_engine.specialists.runtime import SpecialistOutput
    from research_engine.specialists.startup.service import (
        MODES, StartupResearchService)

    svc = StartupResearchService(cfg=rc.orch.cfg,
                                 data_dir=str(rc.orch.cfg.storage.data_dir))
    mode = rc.mode if rc.mode in MODES else "OPPORTUNITY_DISCOVERY"
    ctx = svc.run_mode(rc.api.project_id, mode)

    # Mode contracts vary by design; translate the canonical portfolio shape
    # plus any richer keys the mode chose to include.
    findings: list[dict] = []
    confidence: dict = {}

    portfolio = ctx.get("opportunities", []) or []
    for entry in portfolio[:5]:
        findings.append({
            "text": str(entry.get("problem", ""))[:140],
            "opportunity_id": entry.get("opportunity_id"),
            "total_score": entry.get("total_score"),
            "priority": entry.get("priority"),
            "portfolio_slot": entry.get("portfolio_slot"),
        })
    if portfolio:
        best = max((float(e.get("total_score") or 0)
                    for e in portfolio), default=0.0)
        confidence["opportunity"] = round(min(1.0, best), 3)

    if ctx.get("market") is not None:
        findings.insert(0, {"text":
                            f"market defined: "
                            f"{getattr(ctx['market'], 'name', '')}",
                            "kind": "market_definition"})
    pains = ctx.get("pains") or []
    if pains:
        confidence["customer_pain"] = min(1.0, len(pains) * 0.2)

    gaps_out = [{"id": g.id, "description": g.description}
                for g in (ctx.get("research_gaps")
                          or ctx.get("gaps_detected") or [])][:5]

    recommendations = []
    if not portfolio:
        recommendations.append({"text": "no opportunity patterns yet — "
                                "run CUSTOMER_RESEARCH / "
                                "COMPETITOR_RESEARCH to strengthen "
                                "evidence"})

    return SpecialistOutput(
        specialist_id="startup", version="1.0",
        project_id=rc.api.project_id,
        findings=findings,
        gaps=gaps_out,
        recommendations=recommendations,
        confidence=confidence,
        next_research=[{"what": g["description"]} for g in gaps_out],
        artifacts={"mode": mode,
                   "patterns_seen": ctx.get("patterns_seen", []),
                   "count": ctx.get("count", len(portfolio)),
                   "stages": [{
                       "stage": f"service:{mode}",
                       "seconds": 0.0,
                       "produced": {"opportunities":
                                    len(portfolio)}},
                   ]})


# ---------------------------------------------------------- registration

def _desc(sid: str, name: str, modes: list[str], perms: set,
          skills: list[str], entity_types: list[str], budgets=None):
    from research_engine.specialists.runtime import (
        SpecialistBudget, SpecialistDescriptor, SpecialistPermission)
    return SpecialistDescriptor(
        specialist_id=sid, name=name, version="1.0",
        supported_modes=modes,
        permissions={SpecialistPermission(p) for p in perms},
        skills=skills, entity_types=entity_types,
        budgets=budgets or SpecialistBudget(),
        source_preferences={
            "literature": ["academic", "openalex", "arxiv", "crossref"],
            "technology": ["academic", "technical_docs", "github"],
            "competitive": ["company", "review_sites", "news"],
            "foresight": ["news", "release_notes", "government"],
            "startup": ["forum", "company", "government", "news"],
        }[sid],
        evaluation_suite=f"evals/specialists/{sid}.json")


def ensure_builtin_specialists(registry=None) -> None:
    """Idempotent registration of the Phase-5 builtin set."""
    from research_engine.specialists.domain_pipelines import (
        competitive_invoke, foresight_invoke, literature_invoke,
        technology_invoke)
    from research_engine.specialists.runtime import get_registry

    READ = ("READ_PROJECT", "READ_EVIDENCE")
    builtins = [
        (_desc("literature", "Literature Research Specialist",
               ["LITERATURE_REVIEW", "GAP_DISCOVERY"],
               READ + ("CREATE_CLAIM", "CREATE_GAP",
                       "CREATE_RESEARCH_TASK"),
               ["paper_mapping", "method_comparison", "gap_detection"],
               ["paper", "method", "dataset"]),
         literature_invoke),
        (_desc("technology", "Technical Feasibility Specialist",
               ["FEASIBILITY"],
               READ + ("CREATE_CLAIM", "CREATE_GAP",
                       "CREATE_RESEARCH_TASK"),
               ["technical_feasibility", "constraint_extraction"],
               ["capability", "constraint"]),
         technology_invoke),
        (_desc("competitive", "Competitive Intelligence Specialist",
               ["COMPETITIVE_ANALYSIS"],
               READ + ("CREATE_GAP",),
               ["competitive_analysis"],
               ["competitor_profile", "pricing_plan"]),
         competitive_invoke),
        (_desc("foresight", "Technology Foresight Specialist",
               ["TREND_SCAN"],
               READ + ("CREATE_GAP",),
               ["technology_forecasting"],
               ["tech_shift", "trend_signal"]),
         foresight_invoke),
        (_desc("startup", "Startup Research Specialist",
               ["MARKET_DISCOVERY", "CUSTOMER_RESEARCH",
                "COMPETITOR_RESEARCH", "OPPORTUNITY_DISCOVERY",
                "OPPORTUNITY_DUE_DILIGENCE", "VALIDATION_PLANNING",
                "STARTUP_COMPARISON", "ANALYZE"],
               READ + ("CREATE_CLAIM", "CREATE_GAP", "CREATE_OPPORTUNITY",
                       "CREATE_REPORT"),
               ["market_mapping", "opportunity_detection"],
               ["market", "persona", "competitor_profile", "pricing_plan",
                "opportunity"]),
         startup_invoke),
    ]

    reg = registry or get_registry()
    for d, fn in builtins:
        if reg.lookup(d.specialist_id) is None:
            reg.register(d, fn)
