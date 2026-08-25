"""ResearchService / ProjectService: project lifecycle + research jobs."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from research_engine.models.job import (
    JobPriority, JobStatus, JobTask, ResourceProfile, ResearchJob,
)
from research_engine.platform.errors import ClassifiedError, ErrorCategory


class NotFoundError(ClassifiedError):
    def __init__(self, kind: str, ident: str):
        super().__init__(ErrorCategory.USER, f"{kind} not found: {ident}")


class ConflictError(Exception):
    pass


# --------------------------------------------------------------------- DTOs
class ProjectCreate(BaseModel):
    question: str = Field(min_length=8, max_length=2000)
    mode: str = Field(default="academic", pattern="^(academic|startup)$")


class ResearchStart(BaseModel):
    max_iterations: int | None = None
    priority: int = JobPriority.NORMAL


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=8, ge=1, le=50)


class Page(BaseModel):
    items: list
    total: int
    offset: int
    limit: int


def paginate(items: list, offset: int = 0, limit: int = 50) -> Page:
    return Page(items=items[offset:offset + limit], total=len(items),
                offset=offset, limit=limit)


class ProjectService:
    def __init__(self, ctx):
        self.ctx = ctx

    def create(self, req: ProjectCreate) -> dict:
        from research_engine.core.orchestrator import Orchestrator
        orch = Orchestrator.create_project(self.ctx.cfg, req.question.strip(),
                                           req.mode)
        return json.loads(orch.project.model_dump_json())

    def get(self, project_id: str) -> dict:
        p = self._load_project(project_id)
        out = json.loads(p.model_dump_json())
        out["report_files"] = sorted(
            f.name for f in Path(self.ctx.data_dir, project_id, "reports").glob("*.md")
        ) if Path(self.ctx.data_dir, project_id, "reports").exists() else []
        return out

    def list_projects(self) -> list[dict]:
        """BUG-12 fix: a project.json ghost (no authoritative DB row) is
        excluded, so list() and get() can never disagree about existence."""
        root = Path(self.ctx.data_dir)
        out = []
        for pj in sorted(root.glob("proj_*/project.json")):
            try:
                data = json.loads(pj.read_text())
                pid = data.get("id")
                if not pid or not self._has_db_row(pid):
                    continue   # orphaned workspace: not a real project
                out.append({"id": pid, "question": data.get("question_raw"),
                            "state": data.get("state"),
                            "mode": data.get("mode"),
                            "updated_at": data.get("updated_at")})
            except (OSError, ValueError, KeyError):
                continue
        return out

    def _has_db_row(self, project_id: str) -> bool:
        db_path = Path(self.ctx.data_dir) / project_id / "db.sqlite"
        if not db_path.exists():
            return False
        try:
            import sqlite3
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                row = conn.execute(
                    "SELECT 1 FROM projects WHERE id=? LIMIT 1",
                    (project_id,)).fetchone()
                return row is not None
            finally:
                conn.close()
        except sqlite3.Error:
            return False

    def status(self, project_id: str) -> dict:
        from research_engine.core.orchestrator import Orchestrator
        orch = Orchestrator.load(self.ctx.cfg, project_id)
        p = orch.project
        rrepos = _rrepos(orch)
        return {
            "id": p.id,
            "state": p.state.value if hasattr(p.state, "value") else str(p.state),
            "iteration": p.current_iteration,
            "stop_reason": p.stop_reason.value if p.stop_reason else None,
            "review_gate_pending": p.review_gate_pending,
            "budget": {
                "queries_left": orch.budget.queries_left(),
                "documents_left": orch.budget.documents_left(),
                "llm_calls_left": orch.budget.llm_calls_left(),
                "exhausted": orch.budget.exhausted(),
            },
            "counts": {
                "sources": orch.repos.sources.count(p.id),
                "evidence": orch.repos.evidence.count(p.id, "status!='REJECTED'"),
                "claims": orch.repos.claims.count(p.id),
                "gaps_open": orch.repos.gaps.count(p.id, "resolved=0"),
                "contradictions": orch.repos.contradictions.count(p.id),
                "hypotheses": rrepos.hypotheses.count(p.id),
            },
            # spec #110: meaningful progress measures, never fake percentages
            "progress": _research_progress(orch),
        }

    def pause(self, project_id: str) -> bool:
        """Pause = request cooperative stop of running job(s) for this project."""
        stopped = False
        for job in self.ctx.platform_db.incomplete_jobs():
            if job.project_id == project_id:
                self.ctx.scheduler.pause_job(job.id)
                stopped = True
        return stopped

    def resume(self, project_id: str) -> dict:
        from research_engine.core.orchestrator import Orchestrator
        resumed_jobs = []
        for job in self.ctx.platform_db.list_jobs(project_id=project_id):
            if job.status == JobStatus.PAUSED:
                self.ctx.scheduler.resume_job(job.id)
                resumed_jobs.append(job.id)
        if not resumed_jobs:
            orch = Orchestrator.load(self.ctx.cfg, project_id)
            if orch.project.review_gate_pending or \
               orch.project.state.value == "PAUSED":
                job = self.start_research(
                    ResearchStart(), project_id=project_id, resume=True)
                resumed_jobs.append(job.id)
        return {"resumed_jobs": resumed_jobs}

    def cancel(self, project_id: str) -> int:
        n = 0
        for job in self.ctx.platform_db.incomplete_jobs():
            if job.project_id == project_id:
                self.ctx.scheduler.cancel_job(job.id)
                n += 1
        return n

    def delete(self, project_id: str) -> None:
        """Refuse to delete projects with active work; archive instead (#61)."""
        for job in self.ctx.platform_db.incomplete_jobs():
            if job.project_id == project_id:
                raise ConflictError("project has active jobs")
        import shutil
        shutil.rmtree(Path(self.ctx.data_dir, project_id), ignore_errors=True)

    def _load_project(self, project_id: str):
        from research_engine.core.orchestrator import Orchestrator
        try:
            return Orchestrator.load(self.ctx.cfg, project_id).project
        except FileNotFoundError as exc:
            raise NotFoundError("project", project_id) from exc


class NotFoundError(ClassifiedError):
    def __init__(self, kind: str, ident: str):
        super().__init__(ErrorCategory.USER, f"{kind} not found: {ident}")


class ConflictError(Exception):
    pass


class ResearchService:
    def __init__(self, ctx):
        self.ctx = ctx

    def start(self, project_id: str, req: ResearchStart | None = None,
              resume: bool = False) -> ResearchJob:
        """Queue a long-running research job (spec #25/#5). Returns immediately."""
        from research_engine.core.orchestrator import Orchestrator
        req = req or ResearchStart()
        orch = Orchestrator.load(self.ctx.cfg, project_id)
        if not resume and orch.project.state.value in ("COMPLETED", "CONVERGED") \
           and not req.max_iterations:
            raise ConflictError("research already converged; use resume or "
                                "incremental update")
        job = ResearchJob(project_id=project_id, type="deep_research",
                          priority=req.priority,
                          config_snapshot={"max_iterations": req.max_iterations})
        tasks = [JobTask(job_id=job.id, project_id=project_id, type="DEEP_RESEARCH",
                         resource_profile=ResourceProfile.LLM_LARGE,
                         priority=req.priority,
                         payload={"project_id": project_id,
                                  "max_iterations": req.max_iterations})]
        self.ctx.scheduler.submit_job(job, tasks)
        if not getattr(self.ctx.scheduler, "_threads", []):
            self.ctx.start_scheduler()
        return job

    def ask(self, project_id: str, req: QueryRequest) -> dict:
        """Grounded Q&A over the project's evidence memory (inline, fast)."""
        from research_engine.core.orchestrator import Orchestrator
        from research_engine.memory.qa import GroundedQA
        from research_engine.memory.retrieval import build_retriever
        orch = Orchestrator.load(self.ctx.cfg, project_id)
        # P0-05 fix: GroundedQA(repos, retriever, provider) — the previous
        # call site passed (provider, repos) and crashed 100% of the time.
        qa = GroundedQA(orch.repos, build_retriever(self.ctx.cfg, orch.repos),
                        orch.router.reasoning)
        resp = qa.ask(project_id, req.query, top_k=req.top_k)
        return {"question": resp.question, "answer": resp.answer,
                "confidence": resp.confidence, "insufficient": resp.insufficient,
                "unknowns": resp.unknowns,
                "evidence": [{"id": e.id, "quote": e.quote[:200],
                              "url": e.source_url} for e in getattr(resp, "evidence", [])]}

    def search_memory(self, project_id: str, req: QueryRequest) -> list[dict]:
        from research_engine.memory.retrieval import build_retriever
        orch = Orchestrator.load(self.ctx.cfg, project_id)
        retr = build_retriever(self.ctx.cfg, orch.repos)
        result = retr.retrieve(project_id, req.query, top_k=req.top_k)
        out = []
        for item in (result.items or []):
            out.append({"entity_id": item.entity_id,
                        "score": round(item.score, 4),
                        "components": {k: str(v)[:200]
                                       for k, v in item.components.items()}})
        return out


def _rrepos(orch):
    from research_engine.storage.reasoning_repos import ReasoningRepos
    if not hasattr(orch, "_rrepos"):
        orch._rrepos = ReasoningRepos(orch.db)
    return orch._rrepos


def _research_progress(orch) -> dict:
    """Spec #110: coverage-based progress, no invented percentages."""
    p = orch.project
    plan = orch.repos.plans.all(p.id)
    plan = plan[-1] if plan else None
    branches = plan.branches if plan else []
    answered = sum(1 for b in branches if b.status == "answered")
    gaps_open = [g for g in orch.repos.gaps.all(p.id) if not g.resolved]
    high_gaps = [g for g in gaps_open if g.importance >= 0.6]
    hyps = _rrepos(orch).hypotheses.all(p.id)
    return {
        "branches_total": len(branches),
        "branches_answered": answered,
        "high_priority_gaps_open": len(high_gaps),
        "gaps_open_total": len(gaps_open),
        "hypotheses_under_test": len([h for h in hyps
                                      if h.status in ("UNDER_REVIEW", "TESTABLE")]),
    }
