"""Watcher management service (spec #17-20/#131-133)."""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from research_engine.models.job import Watcher
from research_engine.services.research_service import NotFoundError


class WatcherCreate(BaseModel):
    project_id: str
    name: str = ""
    query: str = Field(min_length=3, max_length=500)
    source_scope: list[str] = Field(default_factory=lambda: ["web"])
    frequency_hours: float = Field(default=24.0, gt=0.01)
    change_policy: str = "content_hash"
    action: str = "incremental_update"


class WatcherService:
    def __init__(self, ctx):
        self.ctx = ctx

    def create(self, req: WatcherCreate) -> dict:
        w = Watcher(project_id=req.project_id, name=req.name,
                    query=req.query, source_scope=req.source_scope,
                    frequency_hours=req.frequency_hours,
                    change_policy=req.change_policy, action=req.action)
        self.ctx.platform_db.save_watcher(w)
        return w.model_dump(mode="json")

    def list(self, project_id: str = "") -> list[dict]:
        return [w.model_dump(mode="json") for w in
                self.ctx.platform_db.list_watchers(project_id)]

    def run_now(self, watcher_id: str) -> dict:
        w = self.ctx.platform_db.get_watcher(watcher_id)
        if w is None:
            raise NotFoundError("watcher", watcher_id)
        from research_engine.platform.watchers import WatchRunner
        summary = WatchRunner(self.ctx, self.ctx.bus).tick(
            w, self.ctx.scheduler.control_flag)
        return summary

    def enable(self, watcher_id: str, enabled: bool) -> dict:
        w = self.ctx.platform_db.get_watcher(watcher_id)
        if w is None:
            raise NotFoundError("watcher", watcher_id)
        w.enabled = enabled
        self.ctx.platform_db.save_watcher(w)
        return {"id": watcher_id, "enabled": enabled}

    def due(self) -> list[dict]:
        return [w.model_dump(mode="json")
                for w in self.ctx.platform_db.due_watchers()]

    def schedule_due(self) -> int:
        """Queue BACKGROUND tick jobs for every due watcher (spec #17).
        Called by the platform loop; returns number of jobs queued."""
        n = 0
        for w in self.ctx.platform_db.due_watchers():
            from research_engine.services.knowledge_service import \
                ResearchJobFactory
            ResearchJobFactory.watcher_tick_job(self.ctx, w.id, w.project_id)
            n += 1
        if n:
            from research_engine.services.context import ServiceContext  # noqa: F401
        return n
