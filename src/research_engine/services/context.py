"""Application service layer (spec #71-73).

Single source of truth for every external interface:

    CLI ─┐
    API ─┼→ Services → Orchestrator/Repos → SQLite
    MCP ─┘

Services own workflow decisions (create job vs answer inline). They never
touch HTTP or stdio concerns, and interfaces never touch SQLite directly.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_engine.core.config import AppConfig
from research_engine.models.job import (
    JobPriority, JobStatus, JobTask, ResourceProfile, ResearchJob,
)
from research_engine.platform.events import DomainEvent, EventBus, global_bus
from research_engine.storage.platform_db import PlatformDB


class ServiceContext:
    """Wires config + platform stores once; services hang off this."""

    def __init__(self, cfg: AppConfig | None = None,
                 data_dir: str | None = None):
        self.cfg = cfg or AppConfig.load()
        self.data_dir = str(data_dir or self.cfg.storage.data_dir)
        self.cfg.storage.data_dir = self.data_dir
        self.platform_db = PlatformDB(self.data_dir)
        self.bus = global_bus()
        self._persister = None
        self._start_event_persistence()
        self._scheduler = None
        self._lock = threading.Lock()

    # -- scheduler lifecycle -------------------------------------------------
    @property
    def scheduler(self):
        with self._lock:
            if self._scheduler is None:
                from research_engine.platform.scheduler import (
                    PersistentScheduler, SchedulerConfig,
                )
                scfg = SchedulerConfig.from_app_config(self.cfg)
                self._scheduler = PersistentScheduler(
                    self.platform_db, scfg, bus=self.bus)
                self._wire_runners()
            return self._scheduler

    def start_scheduler(self) -> None:
        self.scheduler.start()

    def _start_event_persistence(self) -> None:
        try:
            from research_engine.platform.events import EventPersister
            self._persister = EventPersister(self.platform_db, self.bus)
        except Exception:
            pass   # audit persistence degrades gracefully

    def stop_scheduler(self) -> None:
        if self._scheduler is not None:
            self._scheduler.stop()
        if getattr(self, "_persister", None) is not None:
            self._persister.stop()

    def _wire_runners(self) -> None:
        from research_engine.platform.job_runners import (
            make_deep_research_runner, make_experiment_runner, make_report_runner,
        )
        s = self._scheduler
        assert s is not None
        dr = make_deep_research_runner(self.cfg, self.bus)
        s.register_runner("DEEP_RESEARCH", lambda t: dr(t, s.control_flag))
        ex = make_experiment_runner(self.cfg)
        s.register_runner("RUN_EXPERIMENT", lambda t: ex(t, s.control_flag))
        rp = make_report_runner(self.cfg)
        s.register_runner("REGENERATE_REPORT", lambda t: rp(t))
        wr = _make_watcher_tick_runner(self)
        s.register_runner("WATCHER_TICK", lambda t: wr(t))
        iu = _make_incremental_update_runner(self)
        s.register_runner("INCREMENTAL_UPDATE", lambda t: iu(t))


_ctx: ServiceContext | None = None
_ctx_lock = threading.Lock()


def get_context(cfg: AppConfig | None = None,
                data_dir: str | None = None) -> ServiceContext:
    global _ctx
    with _ctx_lock:
        if _ctx is None or cfg is not None or data_dir is not None:
            _ctx = ServiceContext(cfg, data_dir)
        return _ctx


def reset_context() -> None:
    global _ctx
    with _ctx_lock:
        if _ctx is not None and _ctx._scheduler is not None:
            _ctx.stop_scheduler()
        _ctx = None


def _make_watcher_tick_runner(ctx: "ServiceContext"):
    from research_engine.models.job import Watcher as WatcherModel
    from research_engine.platform.watchers import WatchRunner

    def runner(task) -> dict:
        w = ctx.platform_db.get_watcher(task.payload["watcher_id"])
        if w is None:
            return {"status": "MISSING"}
        return WatchRunner(ctx, ctx.bus).tick(w, ctx.scheduler.control_flag)
    return runner


def _make_incremental_update_runner(ctx: "ServiceContext"):
    """Incremental update job (spec #19): refresh watched sources — never a
    full rerun. New/changed docs only."""
    from research_engine.platform.watchers import WatchRunner

    def runner(task) -> dict:
        pid = task.payload.get("project_id") or task.project_id
        wr = WatchRunner(ctx, ctx.bus)
        touched = 0
        for w in ctx.platform_db.list_watchers(project_id=pid):
            if w.enabled:
                summary = wr.tick(w, ctx.scheduler.control_flag)
                touched += summary.get("new", 0) + summary.get("changed", 0)
        return {"sources_touched": touched}
    return runner
