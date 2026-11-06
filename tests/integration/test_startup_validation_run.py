"""startup_validation through the REAL orchestrator run (dispatch + report), offline."""
from __future__ import annotations

from research_engine.models.enums import ProjectState
from research_engine.specialists.startup.idea import build_idea_question

CARD = build_idea_question(
    "AI bookkeeping assistant for small Indian retailers",
    problem="small retailers spend hours on manual GST bookkeeping entries in spreadsheets",
    customer_segment="small business retailers in India",
    alternative="Tally and Excel spreadsheets plus accountants")


def test_full_run_dispatches_to_the_validation_pipeline_and_writes_the_report(
        cfg, fake_registry, make_orchestrator):
    orch = make_orchestrator(CARD, mode="startup_validation")
    orch.repos.projects.save(orch.project)
    p = orch.run()
    assert p.state == ProjectState.COMPLETED
    report = orch.ws.reports / "idea_evaluation.md"
    assert report.exists(), "idea_evaluation.md is produced by the real run"
    text = report.read_text(encoding="utf-8")
    assert "## Verdict:" in text and "AI bookkeeping assistant" in text
    # the discovery-style opportunity_map must not be produced for a single stated idea
    assert not (orch.ws.reports / "opportunity_map.md").exists()
    opps = orch.repos.opportunities.all(p.id)
    assert len(opps) == 1 and opps[0].notes.startswith("USER_IDEA")
    log_text = (orch.ws.reports / "research_log.md").read_text(encoding="utf-8")
    assert "startup specialist failed" not in log_text, log_text[-500:]
    assert "Startup specialist:" in log_text, "the specialist step ran and was logged"


def test_plain_startup_mode_is_unchanged(cfg, fake_registry, make_orchestrator):
    orch = make_orchestrator("Find promising startup opportunities in AI bookkeeping for Indian SMBs",
                             mode="startup")
    orch.repos.projects.save(orch.project)
    orch.run()
    assert not (orch.ws.reports / "idea_evaluation.md").exists()
