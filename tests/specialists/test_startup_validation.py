"""startup_validation engine: end-to-end offline behaviour of the idea evaluation.

Fully offline (fakes + deterministic fallbacks), same style as test_startup_specialist.
"""
from __future__ import annotations

import pytest

from research_engine.core.config import AppConfig
from research_engine.core.orchestrator import Orchestrator
from research_engine.models.evidence import Evidence
from research_engine.models.research import Source
from research_engine.specialists.startup.idea import build_idea_question

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
    ("https://review.example.com/r1", "Users complain Zoho Books lacks integration with regional "
     "payment platforms and is confusing", 5),
]

CARD_FIELDS = dict(
    problem="small retailers spend hours on manual GST bookkeeping entries in spreadsheets",
    customer_segment="small business retailers in India",
    alternative="Tally and Excel spreadsheets plus accountants",
    price_point="Rs 500 per month",
)
IDEA = "AI bookkeeping assistant for small Indian retailers"


def _project(tmp_path, question, evidence=EVIDENCE):
    cfg = AppConfig.load()
    cfg.storage.data_dir = str(tmp_path)
    cfg.search.web_provider = "none"
    cfg.search.academic_providers = []
    orch = Orchestrator.create_project(cfg, question, mode="startup_validation")
    pid = orch.project.id
    srcs = {}
    for url, claim, tier in evidence:
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
    return orch, cfg


def _svc(cfg, tmp_path):
    from research_engine.specialists.startup.service import StartupResearchService
    return StartupResearchService(cfg=cfg, data_dir=str(tmp_path))


def test_pipeline_evaluates_the_stated_idea_not_discovered_patterns(tmp_path):
    orch, cfg = _project(tmp_path, build_idea_question(IDEA, **CARD_FIELDS))
    out = _svc(cfg, tmp_path).run_validation_pipeline(orch.project.id)
    opps = orch.repos.opportunities.all(orch.project.id)
    assert len(opps) == 1, "exactly the user's idea; no discovered opportunities"
    assert opps[0].notes.startswith("USER_IDEA")
    assert opps[0].customer_segment == CARD_FIELDS["customer_segment"]
    ev = out["evaluation"]
    assert ev["opportunity_id"] == opps[0].id
    assert ev["verdict"]["verdict"] in {
        "NOT_ENOUGH_EVIDENCE", "RESEARCH_MORE", "VALIDATE_NEXT",
        "REFINE_THE_IDEA", "COMPARE_ALTERNATIVES"}
    assert ev["tests"], "validation tests with success and kill thresholds are designed"
    assert all(t["kill"] for t in ev["tests"][:1])


def test_pipeline_is_idempotent(tmp_path):
    orch, cfg = _project(tmp_path, build_idea_question(IDEA, **CARD_FIELDS))
    svc = _svc(cfg, tmp_path)
    svc.run_validation_pipeline(orch.project.id)
    n_tests = len(svc.idea_evaluation_view(orch.project.id)["tests"])
    svc.run_validation_pipeline(orch.project.id)
    assert len(orch.repos.opportunities.all(orch.project.id)) == 1
    assert len(svc.idea_evaluation_view(orch.project.id)["tests"]) == n_tests


def test_undefined_customer_never_gets_a_positive_verdict(tmp_path):
    orch, cfg = _project(tmp_path, build_idea_question(IDEA))
    out = _svc(cfg, tmp_path).run_validation_pipeline(orch.project.id)
    v = out["evaluation"]["verdict"]
    assert v["verdict"] == "DEFINE_THE_IDEA"
    assert v["positive"] is False
    assert "customer_segment" in " ".join(v["reasons"])


def test_idea_with_no_overlapping_evidence_is_speculative_not_refuted(tmp_path):
    unrelated = [("https://x.example.com/a", "Quantum error correction thresholds improved "
                  "with surface codes in superconducting qubits", 2)]
    q = build_idea_question("Subscription crate for pet iguana owners",
                            problem="iguana owners cannot find fresh reptile food",
                            customer_segment="pet iguana owners")
    orch, cfg = _project(tmp_path, q, evidence=unrelated)
    out = _svc(cfg, tmp_path).run_validation_pipeline(orch.project.id)
    opp = orch.repos.opportunities.all(orch.project.id)[0]
    assert opp.evidence_ids == [], "market-wide evidence must not be padded onto the idea"
    assert "SPECULATIVE" in opp.notes
    v = out["evaluation"]["verdict"]
    assert v["verdict"] == "NOT_ENOUGH_EVIDENCE" and not v["positive"]
    assert "not a refutation" in v["meaning"]


def test_counterevidence_coverage_is_measured_not_assumed(tmp_path):
    from research_engine.models.research import ResearchBranch, SearchQuery
    orch, cfg = _project(tmp_path, build_idea_question(IDEA, **CARD_FIELDS))
    svc = _svc(cfg, tmp_path)
    assert svc._counterevidence_searched(orch.repos, orch.project.id) is False
    br = ResearchBranch(project_id=orch.project.id, category="RISKS", question="why do they fail")
    br.ensure_id()
    orch.repos.branches.save(br)
    q = SearchQuery(project_id=orch.project.id, text="startup failures", branch=br.id,
                    executed=True)
    q.ensure_id()
    orch.repos.queries.save(q)
    assert svc._counterevidence_searched(orch.repos, orch.project.id) is True
    q.failed = True   # a failed provider call is not a counterevidence search
    orch.repos.queries.save(q)
    assert svc._counterevidence_searched(orch.repos, orch.project.id) is False


def _first_experiment(orch, svc):
    rrepos = svc._repos_for(svc._orch(orch.project.id))[2]
    opp = orch.repos.opportunities.all(orch.project.id)[0]
    exps = [e for e in rrepos.experiments.all(orch.project.id) if e.opportunity_id == opp.id]
    assert exps, "tests were designed for the idea"
    return rrepos, exps[0]


def test_a_contradicting_test_result_stops_the_idea_via_real_ingestion(tmp_path):
    """The real loop: add-result (ResultIngestor) moves the HYPOTHESIS to CONTRADICTED;
    nothing in the codebase sets Assumption.status, so the verdict must read hypotheses."""
    from research_engine.reasoning.result_ingestion import ResultIngestor
    orch, cfg = _project(tmp_path, build_idea_question(IDEA, **CARD_FIELDS))
    svc = _svc(cfg, tmp_path)
    svc.run_validation_pipeline(orch.project.id)
    assert svc.idea_evaluation_view(orch.project.id)["verdict"]["verdict"] != "STOP_OR_PIVOT"
    rrepos, exp = _first_experiment(orch, svc)
    ResultIngestor(orch.repos, rrepos).ingest(
        orch.project.id, exp.id, ["1 of 200 visitors placed a deposit"],
        {"deposit_conversion": 0.005}, interpretation_hint="contradicts")
    v = svc.idea_evaluation_view(orch.project.id)["verdict"]
    assert v["verdict"] == "STOP_OR_PIVOT" and not v["positive"]
    assert any(r.startswith("contradicted:") for r in v["reasons"])


def test_a_supporting_result_does_not_stop_the_idea(tmp_path):
    from research_engine.reasoning.result_ingestion import ResultIngestor
    orch, cfg = _project(tmp_path, build_idea_question(IDEA, **CARD_FIELDS))
    svc = _svc(cfg, tmp_path)
    svc.run_validation_pipeline(orch.project.id)
    rrepos, exp = _first_experiment(orch, svc)
    ResultIngestor(orch.repos, rrepos).ingest(
        orch.project.id, exp.id, ["22% of visitors placed a deposit"], {"deposit_conversion": 0.22},
        interpretation_hint="supports")
    assert svc.idea_evaluation_view(orch.project.id)["verdict"]["verdict"] != "STOP_OR_PIVOT"


def test_reevaluate_script_rewrites_the_report_without_rerunning_research(tmp_path):
    import importlib.util
    from pathlib import Path
    from research_engine.reasoning.result_ingestion import ResultIngestor
    orch, cfg = _project(tmp_path, build_idea_question(IDEA, **CARD_FIELDS))
    svc = _svc(cfg, tmp_path)
    svc.run_validation_pipeline(orch.project.id)
    rrepos, exp = _first_experiment(orch, svc)
    ResultIngestor(orch.repos, rrepos).ingest(
        orch.project.id, exp.id, ["0 deposits"], {"deposit_conversion": 0.0},
        interpretation_hint="contradicts")
    n_evidence = len(orch.repos.evidence.all(orch.project.id))
    path = Path(__file__).resolve().parents[2] / "scripts" / "validate_idea.py"
    spec = importlib.util.spec_from_file_location("validate_idea", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--reevaluate", orch.project.id], cfg=cfg) == 0
    text = (orch.ws.reports / "idea_evaluation.md").read_text(encoding="utf-8")
    assert "STOP_OR_PIVOT" in text
    assert len(orch.repos.evidence.all(orch.project.id)) == n_evidence, "no research was re-run"


def test_view_is_read_only(tmp_path):
    orch, cfg = _project(tmp_path, build_idea_question(IDEA, **CARD_FIELDS))
    svc = _svc(cfg, tmp_path)
    svc.run_validation_pipeline(orch.project.id)
    def snapshot():
        pid = orch.project.id
        return (len(orch.repos.opportunities.all(pid)), len(orch.repos.evidence.all(pid)),
                orch.repos.opportunities.all(pid)[0].updated_at
                if hasattr(orch.repos.opportunities.all(pid)[0], "updated_at") else None)
    before = snapshot()
    svc.idea_evaluation_view(orch.project.id)
    assert snapshot() == before


def test_report_is_written_and_states_limits(tmp_path):
    orch, cfg = _project(tmp_path, build_idea_question(IDEA, **CARD_FIELDS))
    svc = _svc(cfg, tmp_path)
    svc.run_validation_pipeline(orch.project.id)
    from research_engine.specialists.startup.reports import StartupReportWriter
    path = StartupReportWriter(orch.ws.reports).write_idea_evaluation(
        svc.idea_evaluation_view(orch.project.id))
    text = open(path, encoding="utf-8").read()
    for needle in ("## Verdict:", "## Scorecard", "## Evidence against",
                   "kill:", "What would change this verdict", "not evidence of absence"):
        assert needle in text, needle


def test_engine_report_list_includes_idea_evaluation():
    from research_engine.engines.loader import get_engine
    m = get_engine("startup_validation")
    assert "idea_evaluation" in [d.id for d in m.reports.domain]


def test_no_positive_verdict_without_counterevidence_and_competition(tmp_path):
    """Regression: the report once said VALIDATE_NEXT while listing counterevidence and
    competition as missing, and scored zero researched competitors as strong."""
    orch, cfg = _project(tmp_path, build_idea_question(IDEA, **CARD_FIELDS))
    out = _svc(cfg, tmp_path).run_validation_pipeline(orch.project.id)
    gate = out["evaluation"]["gate"]
    assert not gate["checks"]["counterevidence_searched"]   # nothing adversarial ran here
    assert out["evaluation"]["verdict"]["verdict"] != "VALIDATE_NEXT"
    assert not out["evaluation"]["verdict"]["positive"]


def test_report_flags_unresearched_competition_and_dedupes_tests(tmp_path):
    orch, cfg = _project(tmp_path, build_idea_question(
        IDEA, riskiest_assumption="retailers will trust AI with GST filings", **CARD_FIELDS))
    svc = _svc(cfg, tmp_path)
    svc.run_validation_pipeline(orch.project.id)
    view = svc.idea_evaluation_view(orch.project.id)
    keys = [(t["title"].split("]")[0], t["success"], t["kill"]) for t in view["tests"]]
    assert len(keys) == len(set(keys)), "identical tests must be shown once"
    from research_engine.specialists.startup.reports import StartupReportWriter
    text = open(StartupReportWriter(orch.ws.reports).write_idea_evaluation(view),
                encoding="utf-8").read()
    assert "UNRESEARCHED" in text
    assert "retailers will trust AI with GST filings" in text


@pytest.mark.parametrize("ok,bad", [("validated", "invalidated"), ("verified", "falsified")])
def test_readiness_counts_completed_tests_in_both_status_vocabularies(tmp_path, ok, bad):
    """Regression: readiness() only knew verified/falsified while Assumption.status uses
    validated/invalidated, so a completed test could never raise or lower readiness."""
    orch, cfg = _project(tmp_path, build_idea_question(IDEA, **CARD_FIELDS))
    svc = _svc(cfg, tmp_path)
    svc.run_validation_pipeline(orch.project.id)
    ctx = svc.build_market_context(orch.project.id, persist=False)
    repos, _s, rrepos, _g = ctx["_repos"]
    decisions = ctx["_analyzer_handles"]["decisions"]
    opp = repos.opportunities.all(orch.project.id)[0]
    asm = [a for a in rrepos.assumptions.all(orch.project.id) if a.opportunity_id == opp.id]
    for a in asm:
        a.status = ok
        rrepos.assumptions.save(a)
    r = decisions.readiness(orch.project.id, opp.id, opp.score_breakdown["gate"])
    assert r["level"] == "DECISION_READY"
    assert r["assumptions_tested"]["verified"] == len(asm)
    asm[0].status = bad
    rrepos.assumptions.save(asm[0])
    r = decisions.readiness(orch.project.id, opp.id, opp.score_breakdown["gate"])
    assert r["assumptions_tested"]["falsified"] == 1
    assert r["level"] != "DECISION_READY"
