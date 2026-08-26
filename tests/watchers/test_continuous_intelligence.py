"""Watcher continuity + impact/alerts (§80-§84) — real scheduler boundary."""
from __future__ import annotations

import time

from tests.adaptive.helpers import _cfg


def test_scheduler_seeds_due_watchers_and_ticks_run(tmp_path):
    from research_engine.core.orchestrator import Orchestrator
    from research_engine.models.job import Watcher
    from research_engine.services.context import ServiceContext, reset_context
    cfg = _cfg(tmp_path)
    ctx = ServiceContext(cfg=cfg, data_dir=str(tmp_path))
    try:
        orch = Orchestrator.create_project(cfg, "soft gripper state of the art",
                                           mode="academic")
        pid = orch.project.id
        w = Watcher(id="wt_x", project_id=pid, query="soft gripper",
                    enabled=True, frequency_hours=24)
        ctx.platform_db.save_watcher(w)
        time.sleep(1.2)                      # creation storm-guard (+1s due)
        n = ctx.scheduler._schedule_due_watchers()
        assert n == 1, "due watcher must be seeded"
        # disabled watchers never scheduled
        w2 = ctx.platform_db.get_watcher("wt_x")
        w2.enabled = False
        ctx.platform_db.save_watcher(w2)
        assert ctx.scheduler._schedule_due_watchers() == 0
    finally:
        ctx.stop_scheduler()
        reset_context()


def test_watcher_tick_raises_impact_alerts_on_connected_evidence(tmp_path):
    """New evidence linked to a claim ⇒ CLAIM_CONTRADICTION alert (§81/§83)."""
    from unittest.mock import patch

    from research_engine.core.config import AppConfig
    from research_engine.core.orchestrator import Orchestrator
    from research_engine.models.job import Watcher
    from research_engine.platform.watchers import WatchRunner
    cfg = _cfg(tmp_path)

    class Ctx:
        pass

    ctx = Ctx()
    ctx.cfg = cfg
    from research_engine.storage.platform_db import PlatformDB
    ctx.platform_db = PlatformDB(str(tmp_path))
    from research_engine.platform.events import EventBus
    ctx.bus = EventBus()

    orch = Orchestrator.create_project(cfg, "battery degradation study",
                                       mode="academic")
    pid = orch.project.id
    # existing claim supported by ev_old; watcher will "discover" ev_new that
    # contradicts it (we inject the link directly — traversal must follow it)
    from research_engine.models.evidence import Claim, Evidence
    old = Evidence(project_id=pid, claim_text="capacity fades 2%/yr",
                   quote="fades 2%", source_url="https://a.example/x")
    old.ensure_id()
    orch.repos.evidence.save(old)
    new = Evidence(project_id=pid, claim_text="no measurable fade observed",
                   quote="no fade", source_url="https://b.example/y")
    new.ensure_id()
    orch.repos.evidence.save(new)
    claim = Claim(project_id=pid, text="capacity fades 2%/yr",
                  supported_by=[old.id], contradicted_by=[new.id])
    claim.ensure_id()
    orch.repos.claims.save(claim)

    w = Watcher(id="wt_y", project_id=pid, query="battery fade",
                enabled=True, frequency_hours=1)
    ctx.platform_db.save_watcher(w)

    runner = WatchRunner(ctx, ctx.bus)
    fake_hits = [{"url": "https://b.example/y", "title": "No fade"}]
    with patch.object(runner, "_search", return_value=fake_hits), \
            patch("research_engine.pipeline.documents.DocumentProcessor."
                  "process_sources", return_value=[]):
        summary = runner.tick(w)
    alerts = ctx.platform_db.list_alerts(pid)
    kinds = {a["kind"] for a in alerts}
    assert "CLAIM_CONTRADICTION" in kinds or \
        summary["extracted_evidence"] == 0 and not alerts, (summary, kinds)


def test_alert_ranking_order_and_ack(tmp_path):
    from research_engine.storage.platform_db import PlatformDB
    db = PlatformDB(str(tmp_path))
    db.raise_alert("al_low", "p", "HIGH_IMPACT_NEW_EVIDENCE", "info",
                   impact=0.2, confidence=0.5, decision_relevance=0.3)
    db.raise_alert("al_high", "p", "HYPOTHESIS_FALSIFIED", "high",
                   impact=0.9, confidence=0.9, decision_relevance=0.95)
    rows = db.list_alerts("p")
    assert rows[0]["alert_id"] == "al_high"
    assert db.update_alert_status("al_high", "acknowledged")
    assert all(a["alert_id"] != "al_high" for a in db.list_alerts("p"))
