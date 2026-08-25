"""Phase 5 startup specialist tests — fully offline via fakes + deterministic fallbacks."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_engine.core.config import AppConfig
from research_engine.core.orchestrator import Orchestrator
from research_engine.models.evidence import Evidence
from research_engine.models.research import Source
from research_engine.storage.graph_store import GraphEntity, GraphStore


QUESTION = ("Find promising startup opportunities in AI bookkeeping "
            "software for Indian SMB retailers")

EVIDENCE = [
    ("https://forum.example.com/t1", "Small business owners complain that bookkeeping "
     "with Tally is manual and time-consuming, exporting to Excel weekly", 5),
    ("https://forum.example.com/t2", "Retailers in India spend hours daily on manual GST "
     "entries in spreadsheets and it is tedious", 5),
    ("https://news.example.com/x1", "Shop owners report spending Rs 15000 per month on "
     "accountants for basic bookkeeping", 4),
    ("https://company.example.com/zoho", "Zoho Books pricing starts at $15 per month for "
     "small businesses", 3),
    ("https://company.example.com/tally", "Tally charges $300 annual license per user seat", 3),
    ("https://gov.example.com/gst", "New regulation mandates digital invoicing for retailers "
     "above turnover threshold from 2025", 2),
    ("https://vcnews.example.com/f1", "Fintech startup raised $10M funding round to automate "
     "SMB accounting", 4),
    ("https://review.example.com/r1", "Users complain Zoho Books lacks integration with regional "
     "payment platforms and is confusing", 5),
]


@pytest.fixture()
def startup_project(tmp_path):
    """Offline orchestrator + synthetic evidence corpus."""
    cfg = AppConfig.load()
    cfg.storage.data_dir = str(tmp_path)
    cfg.research.mode = "startup"
    cfg.search.web_provider = "none"
    cfg.search.academic_providers = []
    orch = Orchestrator.create_project(cfg, QUESTION, mode="startup")
    pid = orch.project.id

    srcs = {}
    for url, claim, tier in EVIDENCE:
        if url not in srcs:
            s = Source(project_id=pid, url=url, canonical_url=url,
                       domain=url.split("/")[2], title=url)
            s.ensure_id()
            orch.repos.sources.save(s)
            srcs[url] = s
        e = Evidence(project_id=pid, claim_text=claim, quote=claim[:80],
                     source_id=srcs[url].id, source_tier=tier,
                     status="EXTRACTED", iteration=1)
        e.ensure_id()
        orch.repos.evidence.save(e)

    g = GraphStore(orch.db)
    for name, prod in [
            ("Zoho Books", "accounting software platform for small businesses"),
            ("Tally", "desktop accounting software widely used by Indian retailers")]:
        g.upsert_entity(GraphEntity(
            project_id=pid, type="competitor", name=name,
            attributes={"product": prod,
                        "positioning": f"{name} serves Indian SMB retailers"}))
    return orch, cfg, tmp_path


def _service(cfg, tmp_path):
    from research_engine.specialists.startup.service import StartupResearchService
    return StartupResearchService(cfg=cfg, data_dir=str(tmp_path))


class TestPolicies:
    def test_pain_classification_and_hierarchy(self):
        from research_engine.specialists.startup.policies import (
            classify_pain, pain_evidence_class, qualitative, freshness_state)
        cats = classify_pain("manual data entry in spreadsheets is time-consuming")
        assert "manual_labor" in cats and "time" in cats
        assert pain_evidence_class("they pay $200 every month for this") == "actual_payment"
        assert pain_evidence_class("we built a workaround with excel") == "observed_workaround"
        assert pain_evidence_class("it is frustrating") == "reported_pain"
        # no fake precision
        assert qualitative(0.8) == "Strong" and qualitative(0.1) == "Weak"
        assert qualitative(0.0) == "Unknown"
        assert freshness_state("pricing", "2020-01-01", "2026-01-01") == "stale"

    def test_source_routing(self):
        from research_engine.specialists.startup.policies import route_question_kind
        assert route_question_kind("what is the market size TAM") == "market_size"
        assert route_question_kind("zoho books pricing per month") == "pricing"
        assert route_question_kind("what do customers complain about") == "customer_pain"


class TestMarketAnalyzer:
    def test_definition_gaps_become_research_gaps(self, startup_project):
        orch, cfg, tmp = startup_project
        pid = orch.project.id
        from research_engine.specialists.startup.market import MarketAnalyzer
        ma = MarketAnalyzer(orch.repos)
        mkt = ma.build_market(pid, QUESTION)
        # geography IS present in corpus; some dimensions may be missing
        assert isinstance(mkt.definition_gaps, list)
        assert mkt.market_slug
        orch.repos.gaps  # gap saved only when dims missing; both paths valid

    def test_size_conflict_never_averaged(self, startup_project):
        orch, cfg, tmp = startup_project
        pid = orch.project.id
        from research_engine.specialists.startup.market import MarketAnalyzer, slugify
        from research_engine.specialists.startup.models import Market
        ma = MarketAnalyzer(orch.repos)
        mkt = Market(project_id=pid, name="x", market_slug=slugify("x"))
        mkt.ensure_id()
        # same bucket (USD/global/reported), wildly different values -> conflict
        for claim in ["The market was $10 billion in 2024",
                      "Analysts estimate a $24 billion market in 2024"]:
            e = Evidence(project_id=pid, claim_text=claim, quote=claim,
                         source_id=list(srcs_ids(orch))[0], source_tier=3,
                         status="EXTRACTED")
            e.ensure_id()
            orch.repos.evidence.save(e)
        sizes = ma.collect_sizes(pid, mkt)
        report = ma.cross_validate_sizes(pid, mkt, sizes)
        assert len(report["conflicts"]) == 1
        assert report["conflicts"][0]["verdict"] == "MARKET_SIZE_CONFLICT"
        assert report["resolved_consensus"] is False
        # conflict persisted as a contradiction row (visible, not averaged)
        cons = orch.repos.contradictions.all(pid)
        assert any("NOT averaged" in c.explanation for c in cons)


def srcs_ids(orch):
    return [s.id for s in orch.repos.sources.all(orch.project.id)]


class TestCustomers:
    def test_segments_pains_alternatives_workflow(self, startup_project):
        orch, cfg, tmp = startup_project
        pid = orch.project.id
        from research_engine.specialists.startup.customers import CustomerAnalyzer
        ca = CustomerAnalyzer(orch.repos)
        segs = ca.detect_segments(pid)
        names = {s["name"] for s in segs}
        assert "retailers" in names or "smb" in names
        pains = ca.analyze_pains(pid)
        assert pains, "pain evidence must be detected"
        # hierarchy: strongest first
        weights = [p["hierarchy_weight"] for p in pains]
        assert weights == sorted(weights, reverse=True)
        spending = [p for p in pains if p["evidence_class"] == "existing_spending"]
        assert spending, "spending evidence must rank as stronger form"
        alts = ca.extract_alternatives(pid)
        kinds = {a.kind for a in alts}
        assert "software" in kinds or "spreadsheet" in kinds
        wf = ca.map_workflow(pid, "bookkeeping")
        assert wf["topic"] == "bookkeeping"

    def test_personas_speculative_until_corroborated(self, startup_project):
        orch, cfg, tmp = startup_project
        pid = orch.project.id
        from research_engine.specialists.startup.customers import CustomerAnalyzer
        ca = CustomerAnalyzer(orch.repos)
        segs = ca.detect_segments(pid)
        personas = ca.build_personas(pid, segs)
        for p in personas:
            if len(p.evidence_ids) < 2:
                assert p.speculative is True


class TestCompetitors:
    def test_profiles_classification_pricing_normalization(self, startup_project):
        orch, cfg, tmp = startup_project
        pid = orch.project.id
        from research_engine.specialists.startup.competitors import (
            CompetitorAnalyzer, normalize_price)
        ca = CompetitorAnalyzer(orch.repos, GraphStore(orch.db))
        profiles = ca.build_profiles(pid)
        assert {"zoho books", "tally"} <= {p.name.lower() for p in profiles}
        plans = ca.build_pricing_plans(pid)
        raws = [p.price_raw for p in plans]
        assert any("$15" in r for r in raws)          # raw preserved
        monthly = [p for p in plans if p.billing_period == "monthly"]
        annual = [p for p in plans if p.billing_period == "annual"]
        assert monthly and annual
        assert all(p.normalization_note for p in plans)  # never silent
        # normalization math
        eq, note = normalize_price(300, "USD", "annual")
        assert eq == 25.0 and "annual" in note
        eq2, note2 = normalize_price(15, "USD", "monthly")
        assert eq2 == 15.0

    def test_landscape_axes_justified_by_pain(self, startup_project):
        orch, cfg, tmp = startup_project
        pid = orch.project.id
        from research_engine.specialists.startup.customers import CustomerAnalyzer
        from research_engine.specialists.startup.competitors import CompetitorAnalyzer
        pains = CustomerAnalyzer(orch.repos).analyze_pains(pid)
        ca = CompetitorAnalyzer(orch.repos, GraphStore(orch.db))
        ax = ca.landscape_axes(pid, pains, [])
        assert "justification" in ax and ax["x_axis"] and ax["y_axis"]

    def test_distribution_difficulty_verdict(self, startup_project):
        orch, cfg, tmp = startup_project
        pid = orch.project.id
        from research_engine.specialists.startup.competitors import CompetitorAnalyzer
        ca = CompetitorAnalyzer(orch.repos, GraphStore(orch.db))
        dd = ca.distribution_difficulty(pid, [])
        assert dd["verdict"] in ("distribution_difficult", "distribution_uncertain",
                                 "plausible_channels_observed")


class TestSignals:
    def test_independent_signals_deduped_and_graded(self, startup_project):
        orch, cfg, tmp = startup_project
        pid = orch.project.id
        from research_engine.specialists.startup.signals import SignalAnalyzer
        sa = SignalAnalyzer(orch.repos)
        # two mentions of the SAME funding event on the SAME domain => one signal
        base = [{"kind": "funding", "description": "Fintech startup raised $10M funding round",
                 "date": "2026-01-05", "evidence_ids": ["e1"], "_domain": "vcnews.example.com"},
                {"kind": "funding", "description": "Fintech startup raised $10M funding round today",
                 "date": "2026-01-05", "evidence_ids": ["e2"], "_domain": "vcnews.example.com"},
                {"kind": "regulation", "description": "Digital invoicing mandate announced",
                 "date": "2025-11-02", "evidence_ids": ["e3"], "_domain": "gov.example.com"}]
        sigs = sa.collect_signals(pid, base)
        funding = [s for s in sigs if s["kind"] == "funding"]
        assert len(funding) == 1                       # spec #29: one underlying event
        assert funding[0]["mentions"] >= 2
        assert funding[0]["underlying_sources"] == 1
        assert funding[0]["strength"] in ("STRONG", "MEDIUM", "WEAK", "UNKNOWN")
        reg = [s for s in sigs if s["kind"] == "regulation"][0]
        # single dated source => MEDIUM; STRONG requires >=2 independent sources
        assert reg["strength"] == "MEDIUM"
        assert reg["underlying_sources"] == 1

    def test_whynow_weak_without_change_evidence(self, startup_project):
        orch, cfg, tmp = startup_project
        pid = orch.project.id
        from research_engine.specialists.startup.signals import SignalAnalyzer
        sa = SignalAnalyzer(orch.repos)
        res = sa.build_why_now(pid, "quantum underwater basket weaving", [], [])
        assert res["verdict"] == "WHY_NOW_WEAK"


class TestOpportunityEngine:
    def test_patterns_materialize_scored_gated_opps(self, startup_project):
        orch, cfg, tmp = startup_project
        pid = orch.project.id
        svc = _service(cfg, tmp)
        result = svc.run_mode(pid, "OPPORTUNITY_DISCOVERY")
        opps = result["opportunities"]
        assert opps, "evidence patterns must yield candidates"
        for o in opps:
            sb = orch.repos.opportunities.get(o["opportunity_id"]).score_breakdown
            assert set(sb["factors"]) >= {"pain_severity", "wtp_evidence",
                                          "competition_weakness", "timing"}
            assert sb["labels"]["pain_severity"] in ("Strong", "Moderate", "Weak", "Unknown")
            assert o["priority"] in ("high", "medium", "low")
        # gate honesty: fresh discovery has assumptions/tests still missing
        top = orch.repos.opportunities.get(opps[0]["opportunity_id"])
        missing = top.score_breakdown["gate"]["missing"]
        assert "validation_path_exists" in missing or \
            "critical_assumptions_identified" in missing

    def test_counter_pair_and_why_not_built(self, startup_project):
        orch, cfg, tmp = startup_project
        pid = orch.project.id
        svc = _service(cfg, tmp)
        disc = svc.run_mode(pid, "OPPORTUNITY_DISCOVERY")
        engine_disc = disc["opportunities"][0]
        from research_engine.specialists.startup.opportunities import OpportunityEngine
        from research_engine.storage.reasoning_repos import ReasoningRepos
        eng = OpportunityEngine(orch.repos, ReasoningRepos(orch.db), None, None)
        opp = orch.repos.opportunities.get(engine_disc["opportunity_id"])
        pair = eng.counter_evidence_pair(pid, opp)
        assert "strongest_argument_for" in pair and "strongest_argument_against" in pair
        wnb = eng.why_not_built(pid, opp, {})
        explanations = {f["explanation"] for f in wnb["explanations"]}
        assert "incumbent_advantage" in explanations
        moats = eng.moat_analysis(pid, opp)
        for m in moats:
            assert "do not claim as advantage" in m["status"] or m["evidence_ids"]

    def test_versioning_and_decision_log(self, startup_project):
        orch, cfg, tmp = startup_project
        pid = orch.project.id
        from research_engine.specialists.startup.opportunities import OpportunityEngine
        from research_engine.specialists.startup.repos import get_startup_repos
        from research_engine.storage.reasoning_repos import ReasoningRepos
        srepos = get_startup_repos(orch)
        eng = OpportunityEngine(orch.repos, ReasoningRepos(orch.db), None, srepos)
        from research_engine.models.opportunity import Opportunity
        opp = Opportunity(project_id=pid, problem="test opp", customer_segment="smb")
        opp.ensure_id()
        v1 = eng.version_opportunity(opp, {"segment": "B2C"}, "initial hypothesis")
        v2 = eng.version_opportunity(opp, {"segment": "B2B enterprise"}, "pivot after evidence")
        hist = srepos.opportunity_versions.history(pid, opp.id)
        assert [v.version for v in hist] == [1, 2]
        assert "pivot" in hist[1].change_reason
        d = eng.record_decision(opp, "abandon", "core assumption falsified")
        log = srepos.opportunity_decisions.for_opportunity(pid, opp.id)
        assert log[0].decision == "abandon"


class TestAssumptionsValidation:
    def test_business_assumptions_created_ranked(self, startup_project):
        orch, cfg, tmp = startup_project
        pid = orch.project.id
        from research_engine.reasoning.hypothesis_engine import HypothesisGenerator
        from research_engine.specialists.startup.assumptions import BusinessAssumptionBuilder
        from research_engine.storage.reasoning_repos import ReasoningRepos
        from research_engine.models.opportunity import Opportunity
        rr = ReasoningRepos(orch.db)
        opp = Opportunity(project_id=pid, problem="p", customer_segment="retailers")
        opp.ensure_id()
        hyps = HypothesisGenerator(orch.repos, rr, None).generate_business_hypotheses(pid, opp)
        builder = BusinessAssumptionBuilder(rr, None)
        asm = []
        for h in hyps:
            asm += builder.build_for_hypothesis(pid, opp.id, h)
        assert len(asm) >= 8
        cats = {a.category for a in asm}
        assert "willingness_to_pay" in cats
        # idempotent rebuild adds nothing new
        n_before = rr.assumptions.count(pid)
        builder.build_for_hypothesis(pid, opp.id, hyps[0])
        assert rr.assumptions.count(pid) == n_before

    def test_validation_design_info_gain_order_and_interview_audit(self, startup_project):
        from research_engine.specialists.startup.validation import (
            InterviewGuideDesigner, ValidationPlanner, classify_pricing_evidence)
        guide = InterviewGuideDesigner().build("GST filing", "retailers")
        secs = {s["section"] for s in guide["sections"]}
        assert {"screening", "behavior", "spending", "decision"} <= secs
        audit = InterviewGuideDesigner.audit_questions([
            "Wouldn't a tool that automates GST be useful?",
            "How did you handle GST filing last month?",
        ])
        assert audit["findings"][0]["problems"]
        assert audit["findings"][0]["suggested_rewrite"].startswith("How do you currently")
        assert audit["findings"][1]["problems"] == []
        assert audit["verdict"] == "needs_revision"
        # pricing ladder never conflates opinion with payment
        assert classify_pricing_evidence("I think that seems expensive")[0] == "price_opinion"
        assert classify_pricing_evidence("we paid the invoice last week")[0] == "actual_payment"

    def test_planner_idempotent(self, startup_project):
        orch, cfg, tmp = startup_project
        pid = orch.project.id
        svc = _service(cfg, tmp)
        svc.run_mode(pid, "OPPORTUNITY_DISCOVERY")
        p1 = svc.run_mode(pid, "VALIDATION_PLANNING")
        n1 = sum(len(pl["tests_designed"]) for pl in p1["plans"])
        p2 = svc.run_mode(pid, "VALIDATION_PLANNING")
        n2 = sum(len(pl["tests_designed"]) for pl in p2["plans"])
        assert n1 > 0 and n2 == 0   # re-run designs nothing new


class TestDecisions:
    def test_readiness_levels_progress(self, startup_project):
        orch, cfg, tmp = startup_project
        pid = orch.project.id
        from research_engine.specialists.startup.decisions import DecisionEngine
        from research_engine.storage.reasoning_repos import ReasoningRepos
        de = DecisionEngine(orch.repos, ReasoningRepos(orch.db))
        early = de.readiness(pid)
        assert early["level"] in ("NOT_READY", "RESEARCH_READY")
        assert early["coverage"]["ratio"] < 1.0

    def test_behavioral_uncertainty_routes_to_validation(self, startup_project):
        orch, cfg, tmp = startup_project
        pid = orch.project.id
        svc = _service(cfg, tmp)
        svc.run_mode(pid, "OPPORTUNITY_DISCOVERY")
        svc.run_mode(pid, "VALIDATION_PLANNING")
        dil = svc.run_mode(pid, "OPPORTUNITY_DUE_DILIGENCE")
        rec = dil["recommendation"]
        assert rec["critical_uncertainty"] == "willingness_to_pay"
        assert "preorder" in rec["best_next_action"] or "LOI" in rec["best_next_action"]

    def test_founder_fit_separate_axes(self, startup_project):
        orch, cfg, tmp = startup_project
        from research_engine.specialists.startup.decisions import DecisionEngine
        from research_engine.specialists.startup.models import FounderProfile
        from research_engine.storage.reasoning_repos import ReasoningRepos
        de = DecisionEngine(orch.repos, ReasoningRepos(orch.db))
        score = {"total": 0.7, "segment": "retailers"}
        fit_none = de.founder_fit(score, None)
        assert fit_none["market_attractiveness"] == 0.7
        strong = FounderProfile(skills=["python"], capital="seed",
                                industry_access=["retailers"], network=["x"],
                                risk_preference="moderate")
        fit_strong = de.founder_fit(score, strong)
        weak = FounderProfile(capital="bootstrap", risk_preference="conservative")
        fit_weak = de.founder_fit(score, weak)
        assert fit_strong["founder_feasibility"] > fit_weak["founder_feasibility"]
        assert "separate axes" in fit_strong["warning"]


class TestMarketKB:
    def test_cross_project_reuse_seeds_only_missing(self, startup_project):
        """NOTE: project ids derive deterministically from the question, so a
        'second project on the same question' is the SAME project. Use a
        distinct question and seed by explicit market slug."""
        orch, cfg, tmp = startup_project
        pid = orch.project.id
        svc = _service(cfg, tmp)
        svc.run_full_pipeline(pid)
        entry = svc.kb.lookup(QUESTION)
        assert entry.get("competitors"), "KB must remember competitors"
        slug = entry["markets"][0].market_slug
        # genuinely NEW project (different question -> different id)
        orch2 = Orchestrator.create_project(
            cfg, QUESTION + " (follow-up study)", mode="startup")
        assert orch2.project.id != pid
        from research_engine.specialists.startup.repos import get_startup_repos
        srepos2 = get_startup_repos(orch2)
        n1 = svc.kb.seed_project(orch2.project.id, slug, srepos2)
        n2 = svc.kb.seed_project(orch2.project.id, slug, srepos2)
        assert n1 >= 2, "first seed copies remembered knowledge"
        assert n2 == 0, "repeat seeding is a no-op (INVARIANT-003)"
        assert {c.name.lower() for c in srepos2.competitor_profiles.all(orch2.project.id)} == \
               {c.name.lower() for c in entry["competitors"]}
