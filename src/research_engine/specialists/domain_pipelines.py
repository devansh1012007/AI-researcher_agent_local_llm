"""Builtin domain specialists (Phase 5 §19).

Each specialist is a full multi-stage reasoning pipeline over the SHARED
substrate (context pack + repos via the permissioned API). None of them
retrieves, stores, schedules or reports outside core seams; more research
is requested through CREATE_RESEARCH_TASK (§35).

literature@1.0   — map → method comparison → novelty/gap detection
technology@1.0   — constraint extraction → coverage scoring → risk register
competitive@1.0  — landscape → pricing comparison → change detection
foresight@1.0    — trend scan → impact mapping onto assumptions
startup@1.0      — adapter over StartupResearchService modes
"""
from __future__ import annotations

from research_engine.specialists.pipelines import (
    CONSTRAINT_CATEGORIES, ENABLING_TREND_TERMS, TREND_LEXICON,
    StageTracker, feasibility_confidence, keyword_hits)


# ------------------------------------------------------------ literature

def literature_invoke(rc) -> "SpecialistOutput":
    from research_engine.models.enums import ClaimKind
    from research_engine.specialists.runtime import SpecialistOutput

    st = StageTracker()
    pack = rc.context_pack
    evidence = pack.get("evidence", [])

    topics: dict[str, list[str]] = {}

    def _map() -> dict:
        for e in evidence:
            for w in keyword_hits(e["claim_text"],
                                  ["method", "approach", "dataset",
                                   "benchmark", "survey"]):
                topics.setdefault(w, []).append(e["id"])
        return {"produced": {"topic_clusters": len(topics)},
                "inputs": {"evidence": len(evidence)}}
    res_map = st.run("map", _map)

    def _methods() -> dict:
        method_ev = [e for e in evidence if "method" in
                     e["claim_text"].lower()]
        return {"produced": {"method_statements": len(method_ev)}}
    st.run("method_comparison", _methods)

    gaps_found: list[dict] = []

    def _gaps() -> dict:
        covered_terms = set(topics)
        for term in ("benchmark", "dataset", "comparison"):
            if term not in covered_terms and evidence:
                g = rc.api.create_gap(
                    description=f"Literature gap: no {term} statements "
                                f"found for: {rc.api.question[:60]}",
                    importance=3, evidence_needed=term,
                    recommended_queries=[f"{rc.api.question} {term}"])
                gaps_found.append({"id": g.id, "description": g.description})
        return {"produced": {"gaps": len(gaps_found)}}
    st.run("gap_detection", _gaps)

    claims_out: list[dict] = []
    sup_ids = [e["id"] for e in evidence[:1]]
    if sup_ids:
        cl = rc.api.create_claim(
            text=f"Literature map covers {len(evidence)} extracted "
                 "statements for the objective",
            supported_by=sup_ids, kind=ClaimKind.INFERENCE,
            topic="literature_map")
        claims_out.append({"id": cl.id})

    return SpecialistOutput(
        specialist_id="literature", version="1.0", project_id=rc.api.project_id,
        findings=[{"text": f"mapped {len(evidence)} statements"}],
        claims=claims_out, gaps=gaps_found,
        confidence={"coverage": feasibility_confidence(
            set(topics), {"method", "benchmark", "dataset", "comparison"})},
        next_research=[{"what": g["description"]} for g in gaps_found],
        artifacts={"stages": st.stages})


# ------------------------------------------------------------- technology

def technology_invoke(rc) -> "SpecialistOutput":
    from research_engine.models.enums import ClaimKind
    from research_engine.specialists.runtime import SpecialistOutput

    st = StageTracker()
    pack = rc.context_pack
    evidence = pack.get("evidence", [])

    constraints: dict[str, list[dict]] = {}

    def _extract() -> dict:
        for e in evidence:
            text = f"{e['claim_text']} {e['quote']}".lower()
            for cat, terms in CONSTRAINT_CATEGORIES.items():
                if keyword_hits(text, terms):
                    constraints.setdefault(cat, []).append({
                        "evidence_id": e["id"], "statement":
                            e["claim_text"][:160]})
        return {"produced": {k: len(v) for k, v in constraints.items()}}
    st.run("constraint_extraction", _extract)

    missing: list[str] = []

    def _risks() -> dict:
        for cat in CONSTRAINT_CATEGORIES:
            if cat not in constraints:
                missing.append(cat)
                rc.api.create_gap(
                    description=f"Feasibility unknown: no {cat} "
                                f"constraints evidenced for "
                                f"{rc.api.question[:60]}",
                    importance=4, evidence_needed=cat,
                    recommended_queries=[f"{rc.api.question} {cat} cost "
                                         "and requirements"])
        return {"produced": {"unknown_categories": len(missing)}}
    st.run("risk_register", _risks)

    verdict = feasibility_confidence(set(constraints),
                                     set(CONSTRAINT_CATEGORIES))

    def _verdict_stage() -> dict:
        return {"produced": {"feasibility_coverage": verdict}}
    st.run("feasibility_verdict", _verdict_stage)

    findings = [{"text": f"constraint category '{c}' evidenced by "
                         f"{len(items)} items",
                 "category": c, "evidence_ids":
                     [i["evidence_id"] for i in items]}
                for c, items in sorted(constraints.items())]

    recommendations = [{"text": f"research {m} constraints before "
                                 "committing engineering"}
                       for m in missing]

    return SpecialistOutput(
        specialist_id="technology", version="1.0",
        project_id=rc.api.project_id,
        findings=findings,
        recommendations=recommendations,
        confidence={"technical_feasibility": verdict},
        next_research=[{"what": m} for m in missing],
        artifacts={"stages": st.stages,
                   "constraints": {k: len(v)
                                   for k, v in constraints.items()}})


# ------------------------------------------------------------- competitive

def competitive_invoke(rc) -> "SpecialistOutput":
    from research_engine.specialists.runtime import SpecialistOutput

    st = StageTracker()
    orch = rc.orch
    pid = orch.project.id
    profiles, plans = [], []

    def _landscape() -> dict:
        # §53 entity sharing: reuse startup's competitor tables directly
        srepos = getattr(orch, "_srepos", None)
        if srepos is None:
            try:
                from research_engine.specialists.startup.repos import (
                    get_startup_repos)
                srepos = get_startup_repos(orch)
            except Exception:
                srepos = None
        nonlocal profiles, plans
        if srepos is not None:
            profiles = srepos.competitor_profiles.all(pid)
            plans = srepos.pricing_plans.all(pid)
        return {"produced": {"profiles": len(profiles),
                             "plans": len(plans)},
                "inputs": {"shared_entities": True}}
    st.run("landscape", _landscape)

    def _pricing() -> dict:
        by_comp: dict[str, list] = {}
        for p in plans:
            by_comp.setdefault(p.competitor_name, []).append(p)
        return {"produced": {"vendors_with_pricing": len(by_comp)}}
    st.run("pricing_comparison", _pricing)

    changes: list[dict] = []

    def _changes() -> dict:
        seen_prices: dict[str, set] = {}
        for p in plans:
            key = (p.price_raw or "").strip().lower()
            if not key:
                continue
            seen_prices.setdefault(p.competitor_name, set()).add(key)
        for comp, prices in seen_prices.items():
            if len(prices) > 1:
                changes.append({"competitor": comp,
                                "observed_price_variants": len(prices)})
        return {"produced": {"price_changes_detected": len(changes)}}
    st.run("change_detection", _changes)

    unknowns = 0
    def _unknowns() -> dict:
        nonlocal unknowns
        named = {p.name.lower() for p in profiles}
        for e in rc.context_pack.get("evidence", []):
            t = e["claim_text"].lower()
            if ("alternative" in t or "instead of" in t) and \
                    not any(n in t for n in named):
                unknowns += 1
        if unknowns:
            rc.api.create_gap(
                description=f"Competitive gap: {unknowns} mentioned "
                            "alternatives lack profile records",
                importance=3, evidence_needed="competitor identity")
        return {"produced": {"unidentified_alternatives": unknowns}}
    st.run("identity_gaps", _unknowns)

    findings = [{"text": f"{len(profiles)} competitor profiles; "
                         f"{len(plans)} pricing observations"}]
    if changes:
        findings.extend({"text": f"pricing variants detected for {c['competitor']} "
                                 f"({c['observed_price_variants']})",
                         **c} for c in changes)

    return SpecialistOutput(
        specialist_id="competitive", version="1.0",
        project_id=rc.api.project_id,
        findings=findings,
        confidence={"competitor_coverage": feasibility_confidence(
            {p.classification for p in profiles},
            {"direct", "indirect", "substitute", "potential_entrant"})},
        next_research=([{"what": f"identify alternative #{i+1}"}
                        for i in range(min(unknowns, 3))]),
        artifacts={"stages": st.stages})


# ---------------------------------------------------------------- foresight

def foresight_invoke(rc) -> "SpecialistOutput":
    from research_engine.specialists.runtime import SpecialistOutput

    st = StageTracker()
    pack = rc.context_pack
    evidence = pack.get("evidence", [])
    trends: list[dict] = []

    def _scan() -> dict:
        for e in evidence:
            hits = keyword_hits(f"{e['claim_text']} {e['quote']}",
                                TREND_LEXICON)
            if hits:
                trends.append({
                    "signal": e["claim_text"][:140],
                    "evidence_id": e["id"],
                    "signals_matched": hits[:3],
                    "direction": "enabling" if any(
                        h in ENABLING_TREND_TERMS for h in hits)
                    else "disruptive",
                })
        return {"produced": {"trend_signals": len(trends)}}
    st.run("trend_scan", _scan)

    impacted: list[dict] = []

    def _impact() -> dict:
        orch = rc.orch
        pid = orch.project.id
        opps = []
        try:
            opps = list(orch.repos.opportunities.all(pid))
        except Exception:
            opps = []
        for o in opps:
            for t in trends:
                impacted.append({
                    "opportunity_id": o.id,
                    "trend_evidence_id": t["evidence_id"],
                    "direction": t["direction"]})
        return {"produced": {"impacted_assumptions": len(impacted)}}
    st.run("impact_mapping", _impact)

    return SpecialistOutput(
        specialist_id="foresight", version="1.0",
        project_id=rc.api.project_id,
        findings=[{"text": t["signal"], **{k: v for k, v in t.items()
                                           if k != "signal"}}
                  for t in trends],
        recommendations=[{"text": "monitor enabling trend evidence"}
                         for t in trends
                         if t["direction"] == "enabling"][:3],
        confidence={"trend_signal_strength": min(1.0, len(trends) * 0.2)},
        next_research=([{"what": "verify trend durability"}]
                       if trends else []),
        artifacts={"stages": st.stages, "trends": trends,
                   "impacted": impacted})
