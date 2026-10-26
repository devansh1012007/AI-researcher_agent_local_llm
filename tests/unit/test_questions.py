"""Unit tests for Ask-the-User subsystem, schema v2 migration, quality gate, and provenance (Phase 5, INV-032)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from research_engine.engines.loader import get_engine
from research_engine.models.enums import ProjectState, SourceType
from research_engine.models.project import ResearchProblem, ResearchProject
from research_engine.models.questions import Question, QuestionStatus
from research_engine.pipeline.questions import (
    answer_question,
    filter_valid_questions,
    generate_questions_for_project,
)
from research_engine.storage.database import SCHEMA_VERSION, Database
from research_engine.storage.repositories import Repositories


def test_schema_v2_migration_creates_questions_table_on_v1_db(tmp_path: Path):
    db_file = tmp_path / "legacy_v1.sqlite"
    from research_engine.storage.database import _SCHEMA
    conn = sqlite3.connect(str(db_file))
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '1')")
    conn.execute("CREATE TABLE experiments (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, hypothesis_id TEXT NOT NULL, data TEXT NOT NULL)")
    conn.commit()
    conn.close()

    db = Database(db_file)
    assert SCHEMA_VERSION == 2
    row = db.execute("SELECT value FROM meta WHERE key='schema_version'")[0]
    assert row["value"] == "2"
    repos = Repositories(db)
    q = Question(
        project_id="proj_mig",
        text="Which region?",
        changes="Scopes regulatory queries to region",
        default_assumption="Global",
    )
    repos.questions.save(q)
    loaded = repos.questions.get(q.id)
    assert loaded is not None
    assert loaded.text == "Which region?"


def test_question_quality_gate_drops_empty_changes_inv_032():
    q_bad = Question(project_id="p1", text="Vague question?", changes="   ")
    q_good = Question(
        project_id="p1",
        text="Target SMB or Enterprise?",
        changes="Selects SMB vs Enterprise pricing and distribution branches",
    )
    filtered = filter_valid_questions([q_bad, q_good], max_questions=3)
    assert len(filtered) == 1
    assert filtered[0].text == "Target SMB or Enterprise?"


def test_non_blocking_vs_blocking_and_answer_provenance_inv_032(tmp_path: Path):
    db = Database(tmp_path / "q.sqlite")
    repos = Repositories(db)
    p = ResearchProject(id="proj_q", question_raw="AI bookkeeping software", mode="startup")
    p.ensure_id()
    repos.projects.save(p)
    prob = ResearchProblem(
        project_id=p.id,
        objective="Evaluate AI bookkeeping software",
        research_question="AI bookkeeping software",
        ambiguities=["Target customer segment (SMB vs enterprise) is unspecified"],
    )
    prob.ensure_id()
    repos.problems.save(prob)

    manifest = get_engine("startup")

    # 1. Non-blocking mode: records Assumption(rationale="unanswered_default") and keeps state != PAUSED
    qs = generate_questions_for_project(
        p, prob, manifest, repos, max_questions=2, blocking=False
    )
    assert len(qs) == 1
    assert p.state == ProjectState.CREATED
    updated_prob = repos.problems.all(p.id)[0]
    assert any(a.rationale == "unanswered_default" for a in updated_prob.assumptions)

    # 2. Answering the question overrides assumption and records USER_OBSERVATION at tier 2 (never tier 1)
    answered = answer_question(repos, p.id, qs[0].id, answer_text="Indian SMB retailers")
    assert answered.status == QuestionStatus.ANSWERED
    prob_after = repos.problems.all(p.id)[0]
    assert any(a.overridden for a in prob_after.assumptions)
    assert any(a.rationale == "user override" and "Indian SMB retailers" in a.text for a in prob_after.assumptions)

    src = repos.sources.get(answered.source_id)
    ev = repos.evidence.get(answered.evidence_id)
    assert src is not None and ev is not None
    assert src.source_type == SourceType.USER_OBSERVATION
    assert src.source_tier == 2
    assert ev.source_type == SourceType.USER_OBSERVATION
    assert ev.source_tier == 2
    assert ev.extracted_by == "user_input"

    # 3. Blocking mode: transitions project to PAUSED with review_gate_pending="WAITING_FOR_USER"
    p2 = ResearchProject(id="proj_q2", question_raw="AI bookkeeping", mode="startup")
    p2.ensure_id()
    repos.projects.save(p2)
    prob2 = ResearchProblem(
        project_id=p2.id,
        objective="Evaluate AI bookkeeping",
        research_question="AI bookkeeping",
        ambiguities=["Geography is unspecified"],
    )
    prob2.ensure_id()
    repos.problems.save(prob2)
    qs2 = generate_questions_for_project(
        p2, prob2, manifest, repos, max_questions=2, blocking=True
    )
    assert len(qs2) >= 1
    assert p2.state == ProjectState.PAUSED
    assert p2.review_gate_pending == "WAITING_FOR_USER"
