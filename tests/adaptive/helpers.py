"""Phase 6 §96 test suites. Conventions mirror tests/specialists:
module-local cfg(tmp_path), everything offline, real boundaries."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest


def _cfg(tmp_path):
    from research_engine.core.config import AppConfig
    cfg = AppConfig.load()
    cfg.storage.data_dir = str(tmp_path)
    cfg.search.web_provider = "none"
    cfg.search.academic_providers = []
    return cfg


def _store(tmp_path):
    from research_engine.storage.platform_db import PlatformDB
    return PlatformDB(str(tmp_path))


def _run_deep_research(cfg, ctx, question, mode="academic"):
    from research_engine.core.orchestrator import Orchestrator
    from research_engine.models.job import JobTask, ResearchJob
    from research_engine.platform.job_runners import make_deep_research_runner
    orch = Orchestrator.create_project(cfg, question, mode=mode)
    pid = orch.project.id
    job = ResearchJob(project_id=pid, type="DEEP_RESEARCH")
    task = JobTask(job_id=job.id, type="DEEP_RESEARCH",
                   payload={"project_id": pid}, resource_profile="CPU_LIGHT")
    ctx.platform_db.save_job(job)
    ctx.platform_db.add_task(task)
    runner = make_deep_research_runner(cfg, ctx.bus, platform_db=ctx.platform_db)
    result = runner(task)
    return pid, result
