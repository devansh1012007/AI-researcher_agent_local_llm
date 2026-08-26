"""StartupResearchService: the single entry point for the specialist.

Owns the 8 research modes (spec #53-59) and orchestrates analyzers over the
existing platform services. Business logic lives here; CLI/API/MCP stay thin.

Modes:
    MARKET_DISCOVERY        market map + segments + competitors + trends + gaps
    MARKET_DEEP_DIVE        structure, economics, pricing, regulation, technology
    CUSTOMER_RESEARCH       workflow, jobs, pain, alternatives, spending
    COMPETITOR_RESEARCH     profiles, pricing, distribution, strengths/weaknesses
    OPPORTUNITY_DISCOVERY   evidence patterns -> scored opportunity portfolio
    OPPORTUNITY_DUE_DILIGENCE  verification pass + counterevidence + decision
    VALIDATION_PLANNING     assumptions -> ranked tests -> staged sequence
    STARTUP_COMPARISON      side-by-side matrix + tradeoffs

Every mode returns a structured dict; reports are rendered from it.
"""
from __future__ import annotations

import logging

from research_engine.core.config import AppConfig
from research_engine.specialists.startup.assumptions import BusinessAssumptionBuilder
from research_engine.specialists.startup.competitors import CompetitorAnalyzer
from research_engine.specialists.startup.customers import CustomerAnalyzer
from research_engine.specialists.startup.decisions import DecisionEngine
from research_engine.specialists.startup.kb import MarketKnowledgeBase
from research_engine.specialists.startup.market import MarketAnalyzer
from research_engine.specialists.startup.opportunities import OpportunityEngine
from research_engine.specialists.startup.repos import StartupRepos, get_startup_repos
from research_engine.specialists.startup.signals import SignalAnalyzer
from research_engine.intelligence.startup import StartupIntelligence
from research_engine.storage.graph_store import GraphStore
from research_engine.storage.reasoning_repos import ReasoningRepos
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)

MODES = [
    "MARKET_DISCOVERY", "MARKET_DEEP_DIVE", "CUSTOMER_RESEARCH",
    "COMPETITOR_RESEARCH", "OPPORTUNITY_DISCOVERY",
    "OPPORTUNITY_DUE_DILIGENCE", "VALIDATION_PLANNING", "STARTUP_COMPARISON",
]


class StartupResearchService:
    def __init__(self, cfg: AppConfig | None = None,
                 data_dir: str | None = None):
        self.cfg = cfg or AppConfig.load()
        self.data_dir = data_dir or self.cfg.storage.data_dir
        self._kb: MarketKnowledgeBase | None = None

    # ------------------------------------------------------------- wiring
    def _orch(self, project_id: str):
        from research_engine.core.orchestrator import Orchestrator
        orch = Orchestrator.load(self.cfg, project_id)
        return orch

    def _repos_for(self, orch):
        repos = Repositories(orch.db)
        srepos = get_startup_repos(orch)
        rrepos = ReasoningRepos(orch.db)
        graph = GraphStore(orch.db)
        return repos, srepos, rrepos, graph

    @property
    def kb(self) -> MarketKnowledgeBase:
        if self._kb is None:
            self._kb = MarketKnowledgeBase(self.data_dir)
        return self._kb

    def _analyzers(self, repos, srepos, rrepos, graph, provider,
                   persist: bool = True):
        """When srepos is None every analyzer runs READ-ONLY (INVARIANT-004):
        analysis computes; persistence happens only through a live bundle.
        `persist` gates CORE-table writes explicitly (market gaps/conflicts);
        domain-table writes stay keyed on the live srepos bundle."""
        from research_engine.specialists.startup.validation import ValidationPlanner
        return {
            "market": MarketAnalyzer(repos, provider, srepos, persist=persist),
            "customers": CustomerAnalyzer(repos, provider, srepos),
            "competitors": CompetitorAnalyzer(repos, graph, provider, srepos),
            "signals": SignalAnalyzer(repos, graph, provider, srepos),
            "opportunities": OpportunityEngine(repos, rrepos, provider, srepos),
            "assumptions": BusinessAssumptionBuilder(rrepos, provider),
            "decisions": DecisionEngine(repos, rrepos, srepos),
            "validation_planner": ValidationPlanner(rrepos, srepos),
        }

    # ------------------------------------------------------------- shared build
    def build_market_context(self, project_id: str, seed_kb: bool = True,
                             persist: bool = True) -> dict:
        """Run all analyzers and assemble the full market context dict.
        This is the shared substrate every mode consumes.

        persist=False (INVARIANT-004): analyze against persisted state but
        never write — used by report generation."""
        orch = self._orch(project_id)
        repos, live_srepos, rrepos, graph = self._repos_for(orch)
        provider = orch.router.reasoning if hasattr(orch, "router") else None
        # GATE F-01 REPAIR (INVARIANT-004): srepos=None is the read-only
        # convention every analyzer already honors; the duplicated block that
        # used to clobber this gate was removed. See test_gate_findings F-01.
        srepos = live_srepos if persist else None

        del live_srepos  # naming clarity: only `srepos` is used below
        # cross-project reuse first (spec #93): seed remembered knowledge
        kb_seeded = 0
        if seed_kb and srepos is not None:
            prior = [m for m in srepos.markets.all(project_id)]
            slug = prior[0].market_slug if prior else project_id
            kb_seeded = self.kb.seed_project(project_id, slug, srepos)

        base_signals_extractor = StartupIntelligence(repos, graph,
                                                     persist=persist)
        raw_stats = base_signals_extractor.extract_all(project_id)
        raw_signals = base_signals_extractor.load_startup_entities(
            project_id, "market_signal")

        a = self._analyzers(repos, srepos, rrepos, graph, provider,
                            persist=(srepos is not None))

        question = ""
        proj = orch.repos.projects.get(project_id)
        if proj is not None:
            question = getattr(proj, "question_raw", "") or ""

        market = None
        markets = srepos.markets.all(project_id) if srepos is not None else []
        if markets:
            market = markets[0]
        else:
            # compute in memory even when read-only — reports need the
            # context; only the PERSISTENCE is gated (GATE F-01 repair)
            market = a["market"].build_market(project_id, question or project_id)
            if srepos is not None:
                market = srepos.markets.save_natural(market)

        sizes = a["market"].collect_sizes(project_id, market)
        size_report = a["market"].cross_validate_sizes(project_id, market, sizes)

        segments = a["customers"].detect_segments(project_id)
        pains = a["customers"].analyze_pains(project_id)
        alternatives = a["customers"].extract_alternatives(project_id)
        personas = a["customers"].build_personas(project_id, segments)
        jtbd = a["customers"].build_jtbd(project_id, segments, pains, alternatives)

        competitor_profiles = a["competitors"].build_profiles(
            project_id, [s["name"] for s in segments])
        pricing_plans = a["competitors"].build_pricing_plans(project_id)

        signals = a["signals"].collect_signals(project_id, raw_signals)
        tech_shifts = a["signals"].detect_tech_shifts(project_id)
        whynow = a["signals"].build_why_now(project_id, market.name, signals,
                                            tech_shifts)

        landscape = a["competitors"].landscape_axes(project_id, pains,
                                                    competitor_profiles)
        comp_gaps = a["competitors"].detect_gaps(project_id, competitor_profiles,
                                                 segments, pains)
        channels = []
        seen_channels: dict = {}
        for prof in competitor_profiles:
            for ch_name in prof.distribution_channels:
                from research_engine.specialists.startup.models import DistributionChannel
                ckey = ch_name.lower()
                if ckey in seen_channels:
                    merged = seen_channels[ckey]
                    if prof.name not in merged.used_by:
                        merged.used_by.append(prof.name)
                    continue
                dch = DistributionChannel(
                    project_id=project_id, name=ch_name, used_by=[prof.name],
                    evidence_class=prof.channel_evidence.get(ch_name, "hypothesized"))
                dch.ensure_id()
                if srepos is not None:
                    dch = srepos.distribution_channels.save_natural(dch)
                seen_channels[ckey] = dch
                channels.append(dch)
        dist_difficulty = a["competitors"].distribution_difficulty(project_id, channels)

        return {
            "project_id": project_id, "mode_question": question,
            "market": market, "sizes": sizes, "size_report": size_report,
            "segments": segments, "personas": personas, "pains": pains,
            "alternatives": alternatives, "jtbd": jtbd,
            "competitor_profiles": competitor_profiles,
            "pricing_plans": pricing_plans,
            "landscape": landscape, "competitive_gaps": comp_gaps,
            "channels": channels, "distribution_difficulty": dist_difficulty,
            "signals": signals, "tech_shifts": tech_shifts, "whynow": whynow,
            "raw_extraction_stats": raw_stats,
            "kb_seeded_entities": kb_seeded,
            "_analyzer_handles": a, "_repos": (repos, srepos, rrepos, graph),
        }

    # ------------------------------------------------------------- modes
    def run_mode(self, project_id: str, mode: str, **kw) -> dict:
        if mode not in MODES:
            raise ValueError(f"unknown startup mode {mode!r}; one of {MODES}")
        ctx = self.build_market_context(project_id)
        handler = getattr(self, f"_mode_{mode.lower()}")
        result = handler(ctx, **kw)
        result.setdefault("mode", mode)
        result["project_id"] = project_id
        return result

    # --- MARKET_DISCOVERY (#54)
    def _mode_market_discovery(self, ctx: dict, **kw) -> dict:
        return {
            "market_map": {
                "name": ctx["market"].name,
                "definition_gaps": ctx["market"].definition_gaps,
                "geography": ctx["market"].geography,
            },
            "segments": [{"name": s["name"], "evidence_count": len(s["evidence_ids"])}
                         for s in ctx["segments"]],
            "competitors": [{"name": c.name, "classification": c.classification}
                            for c in ctx["competitor_profiles"]],
            "trends": {"signals": ctx["signals"][:6], "tech_shifts":
                       [t.description[:120] for t in ctx["tech_shifts"][:5]]},
            "open_questions": ([g["reason"] for g in ctx["competitive_gaps"]] +
                               ctx["market"].definition_gaps),
        }

    # --- MARKET_DEEP_DIVE (#55)
    def _mode_market_deep_dive(self, ctx: dict, **kw) -> dict:
        return {
            "market_definition": {"name": ctx["market"].name,
                                  "boundaries": ctx["market"].boundaries,
                                  "exclusions": ctx["market"].exclusions,
                                  "definition_gaps": ctx["market"].definition_gaps},
            "size_estimates": [
                {"value_raw": s.value_raw, "currency": s.currency, "year": s.year,
                 "geography": s.geography, "method": s.method,
                 "conflict_flag": s.conflict_flag} for s in ctx["sizes"]],
            "cross_validation": ctx["size_report"],
            "pricing_landscape": [{"company": p.competitor_name, "raw": p.price_raw,
                                   "model": p.pricing_model,
                                   "normalized_monthly": p.annualized_normalized}
                                  for p in ctx["pricing_plans"]],
            "regulation_note": ctx["market"].regulatory_environment,
            "technology_drivers": [t.description[:140] for t in ctx["tech_shifts"][:6]],
        }

    # --- CUSTOMER_RESEARCH (#56)
    def _mode_customer_research(self, ctx: dict, segment: str = "", **kw) -> dict:
        segs = [s for s in ctx["segments"]
                if not segment or s["name"] == segment] or ctx["segments"]
        topic = ctx["mode_question"] or ctx["market"].name
        workflow = self._workflow_for(ctx, topic)
        return {
            "segments": segs,
            "personas": [{"role": p.role, "decision_authority": p.decision_authority,
                          "speculative": p.speculative, "tools": p.existing_tools}
                         for p in ctx["personas"]],
            "jtbd": [{"segment": j.segment_id, "functional_job": j.functional_job,
                      "current_alternative": j.current_alternative}
                     for j in ctx["jtbd"]],
            "pain_points_ranked": ctx["pains"][:12],
            "current_alternatives": [{"name": a.name, "kind": a.kind,
                                      "evidence_count": len(a.evidence_ids)}
                                     for a in ctx["alternatives"]],
            "workflow_map": workflow,
        }

    def _workflow_for(self, ctx: dict, topic: str) -> dict:
        orch_repos = ctx["_repos"][0]
        from research_engine.specialists.startup.customers import CustomerAnalyzer
        ca = CustomerAnalyzer(orch_repos, None, ctx["_repos"][1])
        return ca.map_workflow(ctx["project_id"], topic.split()[0] if topic else "")

    # --- COMPETITOR_RESEARCH (#57)
    def _mode_competitor_research(self, ctx: dict, competitor: str = "", **kw) -> dict:
        profs = [c for c in ctx["competitor_profiles"]
                 if not competitor or c.name.lower() == competitor.lower()]
        return {
            "profiles": [{"name": c.name, "classification": c.classification,
                          "product": c.product, "business_model": c.business_model,
                          "pricing_summary": c.pricing_summary,
                          "channels": c.distribution_channels,
                          "channel_evidence": c.channel_evidence,
                          "strengths": c.strengths[:3],
                          "weaknesses": c.weaknesses[:4],
                          "funding_signal": c.funding_signal,
                          "traction_note": c.traction_note}
                         for c in profs],
            "landscape_axes": ctx["landscape"],
            "pricing_plans": [{"company": p.competitor_name, "raw": p.price_raw,
                               "period": p.billing_period, "model": p.pricing_model,
                               "note": p.normalization_note}
                              for p in ctx["pricing_plans"]],
            "gaps_detected": ctx["competitive_gaps"],
            "distribution_difficulty": ctx["distribution_difficulty"],
        }

    # --- OPPORTUNITY_DISCOVERY (#31/#32)
    def _mode_opportunity_discovery(self, ctx: dict, max_opportunities: int = 5,
                                    **kw) -> dict:
        repos, srepos, rrepos, graph = ctx["_repos"]
        engine = ctx["_analyzer_handles"]["opportunities"]

        patterns = engine.detect_patterns(ctx["project_id"], ctx)
        by_problem = {o.problem: o
                      for o in repos.opportunities.all(ctx["project_id"])}
        opps = []
        for pat in patterns[:max_opportunities * 2]:
            existing = by_problem.get(pat["pain"])
            if existing is not None:
                # already persisted: refresh scoring/gating, never duplicate
                gctx = _gate_ctx(ctx)
                sb = engine.score_rubric(ctx["project_id"], existing, gctx)
                sb["gate"] = engine.quality_gate(
                    ctx["project_id"], existing, gctx,
                    factors=sb.get("factors"))
                existing.score_breakdown = sb
                repos.opportunities.save(existing)
                entry = {"opportunity": existing, "pattern": pat["pattern"],
                         "counter_pair": engine.counter_evidence_pair(
                             ctx["project_id"], existing),
                         "why_not_built": engine.why_not_built(
                             ctx["project_id"], existing, ctx),
                         "moats": engine.moat_analysis(ctx["project_id"], existing)}
                if all(e["opportunity"].id != existing.id for e in opps):
                    opps.append(entry)
                continue
            if len(opps) >= max_opportunities:
                break
            opp = engine.materialize(ctx["project_id"], pat, ctx, set(by_problem))
            if opp is None:
                continue
            by_problem[opp.problem] = opp
            sb = engine.score_rubric(ctx["project_id"], opp, ctx)
            gctx = _gate_ctx(ctx)
            gate = engine.quality_gate(ctx["project_id"], opp, gctx,
                                       factors=sb.get("factors"))
            sb["gate"] = gate
            opp.score_breakdown = sb
            opp.confidence = sb["factors"]["evidence_strength"]
            repos.opportunities.save(opp)
            pair = engine.counter_evidence_pair(ctx["project_id"], opp)
            wnb = engine.why_not_built(ctx["project_id"], opp, ctx)
            moats = engine.moat_analysis(ctx["project_id"], opp)
            opps.append({"opportunity": opp, "pattern": pat["pattern"],
                         "counter_pair": pair, "why_not_built": wnb,
                         "moats": moats})

        opps.sort(key=lambda d: -(d["opportunity"].score_breakdown.get("total", 0)))
        portfolio = []
        for i, entry in enumerate(opps):
            label = ("strong evidence / moderate competition" if i == 0 else
                     "moderate evidence / lower competition" if i == 1 else
                     "higher upside / higher uncertainty")
            portfolio.append({"opportunity_id": entry["opportunity"].id,
                              "problem": entry["opportunity"].problem[:160],
                              "total_score": entry["opportunity"].score_breakdown["total"],
                              "priority": entry["opportunity"].score_breakdown["gate"]["priority"],
                              "portfolio_slot": label})
        return {"opportunities": portfolio,
                "patterns_seen": sorted({e["pattern"] for e in opps}),
                "count": len(portfolio)}

    # --- OPPORTUNITY_DUE_DILIGENCE (#58)
    def _mode_opportunity_due_diligence(self, ctx: dict, opportunity_id: str = "",
                                        **kw) -> dict:
        repos, srepos, rrepos, graph = ctx["_repos"]
        engine = ctx["_analyzer_handles"]["opportunities"]
        opps = repos.opportunities.all(ctx["project_id"])
        if not opps:
            return {"verdict": "NO_OPPORTUNITIES_TO_VERIFY",
                    "note": "run OPPORTUNITY_DISCOVERY first"}
        opp = next((o for o in opps if o.id == opportunity_id), opps[0])

        verification = {
            "market": bool(ctx["market"]) and not ctx["market"].definition_gaps,
            "customer": bool(ctx["segments"]),
            "pain": any(p["evidence_id"] in set(opp.evidence_ids)
                        for p in ctx["pains"]),
            "competition": bool(ctx["competitor_profiles"]),
            "pricing": bool(ctx["pricing_plans"]),
            "distribution": ctx["distribution_difficulty"]["verdict"],
            "technology": bool(ctx["tech_shifts"]),
            "timing": ctx["whynow"]["verdict"],
            "failure_cases": engine.counter_evidence_pair(ctx["project_id"], opp),
        }
        unknowns = [k for k, v in verification.items() if v in (False, "unknown", [])]
        sb = engine.score_rubric(ctx["project_id"], opp, ctx)
        gate = engine.quality_gate(ctx["project_id"], opp, _gate_ctx(ctx))
        sb["gate"] = gate
        opp.score_breakdown = sb
        repos.opportunities.save(opp)
        opp_assumptions = [a for a in rrepos.assumptions.all(ctx["project_id"])
                           if a.opportunity_id == opp.id]
        readiness = ctx["_analyzer_handles"]["decisions"].readiness(
            ctx["project_id"], opp.id, gate)
        rec = ctx["_analyzer_handles"]["decisions"].recommend(
            ctx["project_id"], opp, gate, readiness, opp_assumptions,
            counter_pair=engine.counter_evidence_pair(ctx["project_id"], opp))
        engine.record_decision(opp, rec["decision"],
                               rec["recommendation_text"][:180],
                               opp.evidence_ids[:3], readiness=readiness["level"])
        return {"opportunity_id": opp.id, "verification": verification,
                "unknowns": unknowns, "rubric": sb, "readiness": readiness,
                "recommendation": rec}

    # --- VALIDATION_PLANNING (#38-43)
    def _mode_validation_planning(self, ctx: dict, opportunity_id: str = "",
                                  **kw) -> dict:
        repos, srepos, rrepos, graph = ctx["_repos"]
        builder = ctx["_analyzer_handles"]["assumptions"]
        planner = ctx["_analyzer_handles"]["validation_planner"]

        opps = repos.opportunities.all(ctx["project_id"])
        if not opps:
            return {"note": "no opportunities discovered yet; nothing to validate"}
        targets = [o for o in opps if not opportunity_id or o.id == opportunity_id][:1]

        out = []
        for opp in targets:
            # ensure the hypothesis chain exists (idempotent) so this mode is
            # self-sufficient even without a prior full-pipeline run
            provider = None
            try:
                orch_h = self._orch(ctx["project_id"])
                provider = getattr(getattr(orch_h, "router", None), "reasoning", None)
            except Exception:
                pass
            self._ensure_business_hypotheses(repos, rrepos, provider,
                                             ctx["project_id"], opp)
            hyps = [h for h in rrepos.hypotheses.by_status(
                ctx["project_id"], "PROPOSED", "SUPPORTED", "REVISED", "TESTED",
                "PARTIALLY_SUPPORTED")
                    if getattr(h, "domain", "") == "startup"]
            # link hypotheses to THIS opportunity via assumption rows when possible
            pairs = []
            asm_all = {}
            for h in hyps:
                asm = builder.build_for_hypothesis(ctx["project_id"], opp.id, h)
                asm_all[h.id] = asm
                pairs.append((h, asm))
            designed = planner.design_and_persist(ctx["project_id"], opp.id, pairs)
            stages = planner.sequence(ctx["project_id"], opp, hyps, asm_all)
            all_asm = [a for lst in asm_all.values() for a in lst]
            biggest = planner.biggest_uncertainty(all_asm)
            out.append({
                "opportunity_id": opp.id,
                "hypotheses_covered": len(pairs),
                "assumptions_created": len(all_asm),
                "tests_designed": designed,
                "staged_sequence": stages,
                "biggest_behavioral_uncertainty": biggest,
                "next_action": ctx["_analyzer_handles"]["decisions"].next_action(
                    ctx["project_id"], opp.id, all_asm)["concrete_next_step"],
            })
        return {"plans": out}

    # --- STARTUP_COMPARISON (#49/#59)
    def _mode_startup_comparison(self, ctx: dict, founder=None, **kw) -> dict:
        repos, srepos, rrepos, graph = ctx["_repos"]
        engine = ctx["_analyzer_handles"]["opportunities"]
        opps = repos.opportunities.all(ctx["project_id"])
        if len(opps) < 2:
            return {"note": "need >=2 opportunities to compare",
                    "available": len(opps)}
        comparison = engine.compare_opportunities(ctx["project_id"], *opps[:4])
        fit_rows = {}
        if founder is not None:
            for o in opps[:4]:
                sb = o.score_breakdown or {}
                sb.setdefault("segment", o.customer_segment)
                fit_rows[o.id] = ctx["_analyzer_handles"]["decisions"].founder_fit(sb, founder)
        return {"comparison": comparison, "founder_fit": fit_rows}

    # ------------------------------------------------------------- pipeline hook
    def _ensure_business_hypotheses(self, repos, rrepos, provider,
                                    project_id: str, opp) -> int:
        """Idempotently create the 4-hypothesis business chain for one
        opportunity (statements are deterministic -> dedupe on statement)."""
        existing = {h.statement[:120].lower()
                    for h in rrepos.hypotheses.all(project_id)
                    if getattr(h, "domain", "") == "startup"}
        seg = opp.customer_segment or "target customers"
        probe = f"{seg} experience the problem frequently enough".lower()
        if any(probe in s for s in existing):
            return 0
        from research_engine.reasoning.hypothesis_engine import HypothesisGenerator
        gen = HypothesisGenerator(repos, rrepos, provider)
        hyps = gen.generate_business_hypotheses(project_id, opp)
        return len(hyps)

    def run_full_pipeline(self, project_id: str) -> dict:
        """Called by the orchestrator at synthesize time (startup mode).
        Discovery -> hypotheses+assumptions -> validation design -> decisions."""
        discovery = self.run_mode(project_id, "OPPORTUNITY_DISCOVERY")

        # business hypothesis chain for top opportunities (idempotent)
        orch = self._orch(project_id)
        repos, srepos, rrepos, graph = self._repos_for(orch)
        provider = orch.router.reasoning if hasattr(orch, "router") else None
        n_hyp = 0
        for t in discovery.get("opportunities", [])[:3]:
            opp = repos.opportunities.get(t["opportunity_id"])
            if opp is not None:
                n_hyp += self._ensure_business_hypotheses(
                    repos, rrepos, provider, project_id, opp)

        validation = self.run_mode(project_id, "VALIDATION_PLANNING")
        diligence = self.run_mode(project_id, "OPPORTUNITY_DUE_DILIGENCE")
        validation.setdefault("business_hypotheses_created", n_hyp)

        # remember reusable knowledge for future projects (spec #93)
        try:
            ctx = self.build_market_context(project_id, seed_kb=False)
            self.kb.remember_market(
                ctx["market"], ctx["competitor_profiles"], ctx["pricing_plans"],
                ctx["channels"])
        except Exception as exc:   # KB write must never fail the run
            log.warning("startup KB remember failed: %s", exc)

        return {"discovery": discovery, "validation": validation,
                "diligence": diligence}

    # ------------------------------------------------- canonical read paths
    def assumption_register(self, project_id: str,
                            opportunity_id: str = "") -> list[dict]:
        """Priority-ranked assumption register (canonical CLI/MCP path)."""
        orch = self._orch(project_id)
        rr = self._repos_for(orch)[2]
        asm = [a for a in rr.assumptions.all(project_id)
               if not opportunity_id or a.opportunity_id == opportunity_id]
        asm.sort(key=lambda a: -a.priority)
        return [{"statement": a.statement[:200], "kind": a.kind,
                 "category": a.category, "status": a.status,
                 "priority": round(a.priority, 3),
                 "importance": a.importance, "uncertainty": a.uncertainty,
                 "impact_of_failure": a.impact_of_failure,
                 "ease_of_testing": a.ease_of_testing}
                for a in asm]

    def recommendation_view(self, project_id: str,
                            opportunity_id: str = "") -> dict:
        """Decision view: recommendation + research efficiency (canonical)."""
        dil = self.run_mode(project_id, "OPPORTUNITY_DUE_DILIGENCE",
                            opportunity_id=opportunity_id)
        rec = dil.get("recommendation") or {}
        orch = self._orch(project_id)
        repos, live_srepos, rrepos, graph = self._repos_for(orch)
        eff = self._decisions(repos, rrepos,
                              get_startup_repos(orch)).research_efficiency(project_id)
        return {"recommendation": rec, "efficiency": eff}

    def _decisions(self, repos, rrepos, srepos=None):
        from research_engine.specialists.startup.decisions import DecisionEngine
        return DecisionEngine(repos, rrepos, srepos)


def _gate_ctx(ctx: dict) -> dict:
    """Quality gate needs pipeline-level flags reflecting REAL state:
    have assumptions been built / tests designed for this project yet?"""
    g = dict(ctx)
    repos, srepos, rrepos, graph = ctx["_repos"]
    g["counterevidence_searched"] = True   # adversarial pass runs in the core loop
    g["assumptions_built"] = rrepos.assumptions.count(ctx["project_id"]) > 0
    g["validation_designed"] = rrepos.experiments.count(ctx["project_id"]) > 0
    g.setdefault("retention_signals", [])
    g.setdefault("moat_candidates", [])
    return g
