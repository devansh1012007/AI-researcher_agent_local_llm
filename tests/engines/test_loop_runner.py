"""Tests for LoopRunner cursor persistence, pause_after, resume, and stop_when evaluation (Phase 3)."""
from __future__ import annotations

from pathlib import Path

from research_engine.core.state_machine import StateMachine
from research_engine.engines.loader import get_engine
from research_engine.engines.manifest import LoopStepSpec, StopConditionSpec
from research_engine.engines.runner import LoopRunner, evaluate_stop_conditions
from research_engine.models.enums import ProjectState, StopReason
from research_engine.models.project import ResearchMetrics, ResearchProject
from research_engine.storage.database import Database
from research_engine.storage.repositories import Repositories


def test_loop_runner_pause_after_and_cursor_resume(tmp_path: Path):
    db = Database(tmp_path / "proj.db")
    repos = Repositories(db)
    sm = StateMachine(repos)
    manifest = get_engine("generic").model_copy(deep=True)
    # Configure pause_after on plan in setup and on evaluate_convergence in per_iteration
    for s in manifest.loop.setup:
        if s.step == "plan":
            s.pause_after = True
            s.gate = "AFTER_INITIAL_RESEARCH_PLAN"
    for s in manifest.loop.per_iteration:
        if s.step == "evaluate_convergence":
            s.pause_after = True
            s.gate = "AFTER_CYCLE"

    p = ResearchProject(id="proj_loop", question_raw="Test loop runner cursor", mode="generic")
    p.ensure_id()
    repos.projects.save(p)

    executed: list[tuple[str, int]] = []

    def _make_handler(step_name: str):
        def _fn(_spec: LoopStepSpec):
            executed.append((step_name, p.current_iteration))
            if step_name == "clarify":
                sm.transition(p, ProjectState.CLARIFYING, "clarify")
            elif step_name == "generate_queries":
                sm.transition(p, ProjectState.PLANNED, "planned")
            elif step_name == "search":
                sm.transition(p, ProjectState.SEARCHING, "search")
            elif step_name == "fetch_and_parse":
                sm.transition(p, ProjectState.FETCHING, "fetch")
            elif step_name == "extract_evidence":
                sm.transition(p, ProjectState.EXTRACTING, "extract")
            elif step_name == "verify_and_dedup":
                sm.transition(p, ProjectState.VERIFYING, "verify")
            elif step_name == "detect_contradictions":
                sm.transition(p, ProjectState.ANALYZING_GAPS, "analyze")
            elif step_name == "generate_followups":
                sm.transition(p, ProjectState.GENERATING_FOLLOWUPS, "followups")
            elif step_name == "write_reports":
                sm.transition(p, ProjectState.CONVERGED, "converged")
                sm.transition(p, ProjectState.SYNTHESIZING, "synth")
                sm.transition(p, ProjectState.COMPLETED, "done")
            return True
        return _fn

    handlers = {s.step: _make_handler(s.step) for s in [
        *manifest.loop.setup, *manifest.loop.per_iteration, *manifest.loop.synthesis
    ]}

    runner = LoopRunner(
        manifest=manifest,
        project=p,
        state_machine=sm,
        step_handlers=handlers,
        on_checkpoint=lambda: repos.projects.save(p),
        max_iterations=1,
    )

    # 1. Run until pause_after on 'plan'
    p = runner.run()
    assert p.state == ProjectState.PAUSED
    assert p.review_gate_pending == "AFTER_INITIAL_RESEARCH_PLAN"
    assert p.loop_cursor["phase"] == "setup"
    assert p.loop_cursor["pending_pause"] is True
    assert [x[0] for x in executed] == ["clarify", "ask_user", "plan"]

    # 2. Resume cursor -> does NOT re-run clarify/ask_user/plan; continues at generate_queries and pauses after evaluate_convergence
    runner.resume_cursor()
    p = runner.run()
    assert p.state == ProjectState.PAUSED
    assert p.review_gate_pending == "AFTER_CYCLE"
    assert "generate_queries" in [x[0] for x in executed]
    assert [x[0] for x in executed].count("clarify") == 1
    assert [x[0] for x in executed].count("plan") == 1

    # 3. Resume cursor again -> finishes iteration 1 and runs synthesis -> COMPLETED
    runner.resume_cursor()
    p = runner.run()
    assert p.state == ProjectState.COMPLETED
    assert p.loop_cursor["phase"] == "completed"
    assert executed[-1][0] == "write_reports"


def test_evaluate_stop_conditions():
    conds = [
        StopConditionSpec(metric="new_evidence_rate", op="<=", value=0.10, after_iteration=2),
        StopConditionSpec(metric="gaps_open", op="==", value=0, after_iteration=1),
    ]
    m1 = ResearchMetrics(project_id="p1", iteration=1, new_evidence_rate=0.05, gaps_open=2)
    matched1, _ = evaluate_stop_conditions(conds, m1, iteration=1)
    assert matched1 is False  # iteration 1 < after_iteration 2 for new_evidence_rate

    m2 = ResearchMetrics(project_id="p1", iteration=2, new_evidence_rate=0.05, gaps_open=2)
    matched2, reason2 = evaluate_stop_conditions(conds, m2, iteration=2)
    assert matched2 is True
    assert "new_evidence_rate" in reason2
