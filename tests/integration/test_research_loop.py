"""Integration: full research loop offline (fake search + fake HTTP + scripted LLM).

Verifies: clarify -> plan -> search -> fetch -> extract -> validate -> store ->
gaps/contradictions -> follow-ups -> convergence -> reports; plus resume.
"""
from __future__ import annotations

import pytest
from fakes import ScriptedLLM

from research_engine.models.enums import ProjectState, StopReason


@pytest.fixture()
def question():
    return "What are the most promising approaches for using LLMs for robotic manipulation planning?"


def test_full_research_loop_offline(cfg, fake_registry, make_orchestrator, question, tmp_path):
    orch = make_orchestrator(question)
    orch.repos.projects.save(orch.project)
    project = orch.run()

    # -- lifecycle completed -------------------------------------------------
    assert project.state == ProjectState.COMPLETED, f"state={project.state}"
    assert project.stop_reason in (StopReason.CONVERGED, StopReason.MAX_ITERATIONS,
                                   StopReason.NO_HIGH_VALUE_GAPS, StopReason.BUDGET_EXHAUSTED)

    # -- problem & plan persisted ---------------------------------------------
    problems = orch.repos.problems.all(project.id)
    assert problems and problems[0].research_question
    assert problems[0].assumptions  # explicit assumption recorded
    plans = orch.repos.plans.all(project.id)
    assert plans and len(plans[-1].branches) >= 3

    # -- queries executed with provenance -------------------------------------
    queries = orch.repos.queries.all(project.id)
    assert queries
    assert all(q.executed for q in queries if q.results_count > 0 or q.executed)
    assert any(q.reason for q in queries)

    # -- sources: discovery + dedup + tiers ------------------------------------
    sources = orch.repos.sources.all(project.id)
    assert sources
    canonical = {s.canonical_url for s in sources}
    assert len(canonical) == len(sources)          # URL dedup at discovery
    assert any(s.source_tier == 1 for s in sources)  # academic providers routed

    # -- documents fetched & parsed --------------------------------------------
    docs = orch.repos.documents.all(project.id)
    assert docs
    assert all(d.content_status == "PARSED" for d in docs)
    chunks = [c for c in orch.repos.chunks.all(project.id)]
    assert chunks

    # -- evidence extracted AND validated ---------------------------------------
    evidence = orch.repos.evidence.all(project.id)
    accepted = [e for e in evidence if e.status.value != "REJECTED"]
    assert accepted, "expected at least some accepted evidence"
    for e in accepted:
        assert e.quote and e.source_id and e.document_id      # provenance chain
        ok, _ = __import__("research_engine.pipeline.evidence",
                           fromlist=["verify_quote"]).verify_quote(
            e.quote, next(c.text for c in chunks if c.id == e.chunk_id))
        assert ok, f"stored evidence failed quote verification: {e.id}"

    # -- claims consolidated ------------------------------------------------------
    claims = orch.repos.claims.all(project.id)
    assert claims
    for c in claims:
        assert c.supported_by, "claims must reference supporting evidence"

    # -- metrics recorded per iteration -------------------------------------------
    metrics = sorted(orch.repos.metrics.all(project.id), key=lambda m: m.iteration)
    assert metrics
    assert metrics[-1].new_evidence_this_iter >= 0

    # -- audit trail ----------------------------------------------------------------
    events = orch.events.read_events()
    kinds = {e["event"] for e in events}
    assert {"problem_clarified", "plan_created",
            "cycle_complete", "analysis_complete"} <= kinds

    # -- reports generated -------------------------------------------------------------
    report_dir = orch.ws.reports
    for name in ("problem.md", "research_plan.md", "info.md", "sources.md",
                 "gaps.md", "research_log.md"):
        assert (report_dir / name).exists(), f"{name} missing"
    info_text = (report_dir / "info.md").read_text()
    assert "Contradictions" in info_text and "Traceability" in info_text
    sources_text = (report_dir / "sources.md").read_text()
    assert "Accepted Sources" in sources_text

    # -- JSONL exports available ---------------------------------------------------------
    ev_export = orch.ws.export_jsonl("evidence", [e.model_dump() for e in evidence])
    assert ev_export.exists()


def test_resume_preserves_state(cfg, fake_registry, make_orchestrator, question):
    orch = make_orchestrator(question)
    orch.repos.projects.save(orch.project)

    # run to completion
    project = orch.run()
    n_evidence = orch.repos.evidence.count(project.id)

    # resume from COMPLETED (continuation path): state machine allows COMPLETED->SEARCHING
    from research_engine.models.enums import ProjectState as PS
    orch.sm.transition(project, PS.SEARCHING, "continuation")
    project2 = orch.run(max_iterations=1)
    # no data lost
    assert orch.repos.evidence.count(project2.id) >= n_evidence


def test_startup_mode_uses_same_core(cfg, fake_registry, make_orchestrator):
    q = "Find promising startup opportunities around AI infrastructure for small businesses in India"
    orch = make_orchestrator(q, mode="startup")
    orch.repos.projects.save(orch.project)
    project = orch.run()
    assert project.state == ProjectState.COMPLETED
    plan = orch.repos.plans.all(project.id)[-1]
    cats = {b.category.value for b in plan.branches}
    startup_cats = {"MARKET", "CUSTOMERS", "PAIN", "COMPETITORS"}
    assert cats & startup_cats, f"expected startup categories, got {cats}"


def test_budget_hard_stop(cfg, fake_registry, make_orchestrator, question):
    cfg.research.max_llm_calls = 12   # tiny budget
    orch = make_orchestrator(question)
    orch.repos.projects.save(orch.project)
    project = orch.run()
    # must stop, not loop forever
    assert project.stop_reason is not None
    assert project.budget.llm_calls_used <= cfg.research.max_llm_calls + 3
