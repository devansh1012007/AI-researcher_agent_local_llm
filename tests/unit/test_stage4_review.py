"""Stage 4: analyst review overlay (C13-C16).

Pins the review-decision behaviour, not the happy path:

- a decision row carries verdict, reviewer label, actor kind, timestamp and
  content hash, scoped to one project (INV-013);
- the verdict vocabulary is closed per target kind and an out-of-vocabulary
  verdict raises loudly (illegal transition);
- latest NON-STALE decision wins; a decision whose content_hash no longer
  matches the target is stale: surfaced in list_decisions, never applied,
  and never displaces a live decision;
- report generation is read-only over primary state (INV-004) and the
  review_decisions table is created additively with no migration.
"""
from __future__ import annotations

import sqlite3

import pytest

from research_engine.models.review import (
    IllegalReviewTransition, content_hash_for,
)
from research_engine.services.context import ServiceContext
from research_engine.services.review_service import ReviewService


def _make_project(tmp_path, question="stage 4 review question"):
    from research_engine.core.config import AppConfig
    from research_engine.core.orchestrator import Orchestrator
    cfg = AppConfig.load()
    cfg.storage.data_dir = str(tmp_path)
    cfg.search.web_provider = "none"
    cfg.search.academic_providers = []
    return Orchestrator.create_project(cfg, question, mode="startup"), cfg


def _claim(orch, text):
    from research_engine.models.evidence import Claim
    c = Claim(project_id=orch.project.id, text=text, kind="FACT")
    c.ensure_id()
    orch.repos.claims.save(c)
    return c


def _svc(orch, cfg):
    ctx = ServiceContext(cfg=cfg, data_dir=cfg.storage.data_dir)
    return ReviewService(ctx)


def test_decision_persists_with_content_hash_and_fields(tmp_path):
    orch, cfg = _make_project(tmp_path)
    claim = _claim(orch, "Retailers complain bookkeeping is manual")
    svc = _svc(orch, cfg)
    out = svc.record_decision(
        orch.project.id, "claim", claim.id, "REJECTED",
        note="not supported by quote", reviewer_label="alice",
        actor_kind="os_user")
    assert out["id"].startswith("rev_")
    assert out["target_kind"] == "claim"
    assert out["target_id"] == claim.id
    assert out["verdict"] == "REJECTED"
    assert out["actor_kind"] == "os_user"
    assert out["reviewer_label"] == "alice"
    assert out["content_hash"] == content_hash_for("claim",
                                                   claim_text=claim.text)
    assert out["decided_at"]


def test_illegal_verdict_raises_loudly(tmp_path):
    orch, cfg = _make_project(tmp_path)
    claim = _claim(orch, "some claim text")
    svc = _svc(orch, cfg)
    # "CONFIRMED" is a contradiction verdict, illegal for a claim.
    with pytest.raises(IllegalReviewTransition):
        svc.record_decision(orch.project.id, "claim", claim.id, "CONFIRMED")
    # unknown target kind is illegal too.
    with pytest.raises(IllegalReviewTransition):
        svc.record_decision(orch.project.id, "not_a_kind", claim.id, "APPROVED")


def test_latest_non_stale_wins(tmp_path):
    orch, cfg = _make_project(tmp_path)
    claim = _claim(orch, "claim text v1")
    svc = _svc(orch, cfg)
    svc.record_decision(orch.project.id, "claim", claim.id, "APPROVED",
                        note="first", actor_kind="os_user")
    svc.record_decision(orch.project.id, "claim", claim.id, "REJECTED",
                        note="second", actor_kind="os_user")
    assert svc.current_verdict(orch.project.id, "claim", claim.id) == "REJECTED"
    decisions = svc.list_decisions(orch.project.id, "claim", claim.id)
    assert [d["verdict"] for d in decisions] == ["APPROVED", "REJECTED"]
    assert all(not d["is_stale"] for d in decisions)


def test_stale_decision_surfaced_never_applied(tmp_path):
    orch, cfg = _make_project(tmp_path)
    claim = _claim(orch, "claim text v1")
    svc = _svc(orch, cfg)
    svc.record_decision(orch.project.id, "claim", claim.id, "REJECTED",
                        note="first", actor_kind="os_user")
    assert svc.current_verdict(orch.project.id, "claim", claim.id) == "REJECTED"
    # Edit the target text -> the recorded content_hash no longer matches.
    claim.text = "claim text v2 EDITED"
    orch.repos.claims.save(claim)
    decisions = svc.list_decisions(orch.project.id, "claim", claim.id)
    assert decisions[0]["is_stale"] is True
    # Stale decision is never applied: current verdict reverts to none.
    assert svc.current_verdict(orch.project.id, "claim", claim.id) is None


def test_reaffirming_current_verdict_is_noop(tmp_path):
    orch, cfg = _make_project(tmp_path)
    claim = _claim(orch, "claim text")
    svc = _svc(orch, cfg)
    svc.record_decision(orch.project.id, "claim", claim.id, "APPROVED",
                        note="first", actor_kind="os_user")
    before = svc.list_decisions(orch.project.id, "claim", claim.id)
    out = svc.record_decision(orch.project.id, "claim", claim.id, "APPROVED",
                              note="re-affirm", actor_kind="os_user")
    after = svc.list_decisions(orch.project.id, "claim", claim.id)
    assert len(before) == len(after), "re-affirmation must not append a row"
    assert out["id"] == before[0]["id"]


def test_content_hash_per_kind(tmp_path):
    # whitespace-collapsed + lowercased => equal
    assert content_hash_for("claim", claim_text="Hello   World") == \
        content_hash_for("claim", claim_text="hello world")
    # genuinely different text => different hash
    assert content_hash_for("claim", claim_text="Hello World") != \
        content_hash_for("claim", claim_text="Goodbye World")
    contra = content_hash_for("contradiction", statement_a="a", statement_b="b")
    plan = content_hash_for("validation_plan", assumption="x",
                            cheapest_test="y")
    assert contra != plan


def test_review_table_created_additively(tmp_path):
    """No migration: review_decisions exists after Database init (INV-023)."""
    from research_engine.storage.database import Database
    from research_engine.storage.workspace import Workspace
    ws = Workspace(str(tmp_path / "data"), "proj")
    db = Database(ws.db_path)
    tables = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "review_decisions" in tables
    db.close()


def test_project_isolation(tmp_path):
    """INV-013: decisions in one project are invisible to another."""
    a, cfg_a = _make_project(tmp_path, "project A")
    b, cfg_b = _make_project(tmp_path, "project B")
    claim_a = _claim(a, "claim A")
    claim_b = _claim(b, "claim B")
    svc_a = _svc(a, cfg_a)
    svc_a.record_decision(a.project.id, "claim", claim_a.id, "APPROVED",
                          actor_kind="os_user")
    svc_b = _svc(b, cfg_b)
    svc_b.record_decision(b.project.id, "claim", claim_b.id, "REJECTED",
                          actor_kind="os_user")
    assert len(svc_a.list_decisions(a.project.id)) == 1
    assert len(svc_b.list_decisions(b.project.id)) == 1
    assert svc_a.list_decisions(a.project.id)[0]["target_id"] == claim_a.id


def test_reject_excludes_claim_from_report_findings(tmp_path):
    """C16: a rejected claim is filtered out of the report's findings-bound
    claims list and explicitly marked in the output."""
    from research_engine.reports.generator import ReportGenerator
    from research_engine.models.research import Source
    from research_engine.models.evidence import Evidence
    orch, cfg = _make_project(tmp_path)
    # a claim WITH supporting evidence would render as a finding if kept
    s = Source(project_id=orch.project.id, url="https://x.example/1",
               canonical_url="https://x.example/1", domain="x.example", title="t")
    s.ensure_id()
    orch.repos.sources.save(s)
    claim_text = "Retailers complain bookkeeping is manual"
    e = Evidence(project_id=orch.project.id, claim_text=claim_text,
                 quote=claim_text[:40], source_id=s.id, source_tier=4,
                 status="EXTRACTED")
    e.ensure_id()
    orch.repos.evidence.save(e)
    claim = _claim(orch, claim_text)
    claim.supported_by = [e.id]
    orch.repos.claims.save(claim)
    svc = _svc(orch, cfg)
    svc.record_decision(orch.project.id, "claim", claim.id, "REJECTED",
                        actor_kind="os_user")
    # filter logic: rejected claim leaves the bound list
    gen = ReportGenerator(cfg, None, orch.repos, orch.ws)
    all_claims = orch.repos.claims.all(orch.project.id)
    filtered, rejected = gen._exclude_rejected_claims(orch.project.id,
                                                      all_claims)
    assert claim.id not in {c.id for c in filtered}
    assert claim.id in rejected
    # report output: marked as rejected, not rendered as a finding
    path = gen.write_info(orch.project)
    content = open(path).read()
    assert "human-rejected" in content and claim.id in content
    assert claim.text[:25] not in content.split("## Review decisions")[0]
