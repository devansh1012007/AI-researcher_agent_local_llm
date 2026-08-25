"""REST API (spec #23-26/#53/#108/#128).

Thin adapter: request validation + service calls + structured errors.
No business logic lives here; the API never touches SQLite.

Security defaults (spec #67): binds localhost only; auth token REQUIRED if
bound externally; untrusted-content boundaries respected downstream.
"""
from __future__ import annotations

import json
import queue as _queue
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from research_engine.platform.errors import ClassifiedError
from research_engine.services.context import ServiceContext
from research_engine.services.research_service import (
    ConflictError, NotFoundError, ProjectCreate, ProjectService,
    QueryRequest, ResearchService, ResearchStart,
)
from research_engine.services.knowledge_service import (
    EvidenceService, ExperimentService, HypothesisService, ReportService,
)


# ------------------------------------------------------------------- schemas
class ErrorResponse(BaseModel):
    error: dict = Field(..., description="structured error body")


class JobRef(BaseModel):
    job_id: str
    status: str


class ApiInfo(BaseModel):
    name: str = "gar-research-platform"
    version: str = "4.0"
    environment: str = "HYBRID"


# ---------------------------------------------------------------- app factory
def create_app(ctx: ServiceContext | None = None) -> FastAPI:
    ctx = ctx  # resolved lazily so tests can inject isolated contexts
    holder = {"ctx": ctx}

    def get_ctx() -> ServiceContext:
        if holder["ctx"] is None:
            from research_engine.services.context import get_context
            holder["ctx"] = get_context()
        return holder["ctx"]

    app = FastAPI(title="GAR Research Platform", version="4.0",
                  description="Local-first evidence-grounded research platform")
    auth = make_auth_dependency(holder)

    # ------------------------------------------------------------- health
    @app.get("/health")
    def health() -> dict:
        return health_report(get_ctx())

    @app.get("/ready")
    def ready() -> dict:
        h = health_report(get_ctx())
        return {"ready": h["status"] != "unavailable",
                "checks": h["checks"]}

    @app.get("/info", response_model=ApiInfo)
    def info() -> ApiInfo:
        return ApiInfo(environment=get_ctx().cfg.platform.effective_environment())

    # ------------------------------------------------------------ projects
    @app.post("/projects", status_code=201)
    def create_project(req: ProjectCreate, _: str = Depends(auth)) -> dict:
        return _guard(lambda: ProjectService(get_ctx()).create(req))

    @app.get("/projects")
    def list_projects(_: str = Depends(auth)) -> list[dict]:
        return ProjectService(get_ctx()).list_projects()

    @app.get("/projects/{project_id}")
    def get_project(project_id: str, _: str = Depends(auth)) -> dict:
        return _guard(lambda: ProjectService(get_ctx()).get(project_id))

    @app.delete("/projects/{project_id}")
    def delete_project(project_id: str, _: str = Depends(auth)) -> dict:
        _guard(lambda: ProjectService(get_ctx()).delete(project_id))
        return {"deleted": project_id}

    @app.post("/projects/{project_id}/run", response_model=JobRef, status_code=202)
    def run_project(project_id: str, req: ResearchStart | None = None,
                    _: str = Depends(auth)) -> JobRef:
        job = _guard(lambda: ResearchService(get_ctx()).start(
            project_id, req or ResearchStart()))
        return JobRef(job_id=job.id, status=job.status)

    @app.post("/projects/{project_id}/pause")
    def pause_project(project_id: str, _: str = Depends(auth)) -> dict:
        ok = ProjectService(get_ctx()).pause(project_id)
        return {"paused": ok}

    @app.post("/projects/{project_id}/resume")
    def resume_project(project_id: str, _: str = Depends(auth)) -> dict:
        return _guard(lambda: ProjectService(get_ctx()).resume(project_id))

    @app.post("/projects/{project_id}/cancel")
    def cancel_project(project_id: str, _: str = Depends(auth)) -> dict:
        n = ProjectService(get_ctx()).cancel(project_id)
        return {"cancelled_jobs": n}

    @app.get("/projects/{project_id}/status")
    def project_status(project_id: str, _: str = Depends(auth)) -> dict:
        return _guard(lambda: ProjectService(get_ctx()).status(project_id))

    # ------------------------------------------------------- knowledge read
    @app.get("/projects/{project_id}/evidence")
    def evidence(project_id: str, offset: int = Query(0, ge=0),
                 limit: int = Query(50, ge=1, le=200),
                 status: str = "",
                 _: str = Depends(auth)) -> dict:
        return _guard(lambda: EvidenceService(get_ctx()).list_evidence(
            project_id, offset, limit, status))

    @app.get("/projects/{project_id}/claims")
    def claims(project_id: str, offset: int = Query(0, ge=0),
               limit: int = Query(50, ge=1, le=200),
               _: str = Depends(auth)) -> dict:
        return _guard(lambda: EvidenceService(get_ctx()).list_claims(
            project_id, offset, limit))

    @app.get("/projects/{project_id}/gaps")
    def gaps(project_id: str, _: str = Depends(auth)) -> dict:
        return _guard(lambda: EvidenceService(get_ctx()).list_gaps(project_id))

    @app.get("/projects/{project_id}/contradictions")
    def contradictions(project_id: str, _: str = Depends(auth)) -> list[dict]:
        return _guard(lambda: EvidenceService(get_ctx()).contradictions(project_id))

    @app.get("/projects/{project_id}/hypotheses")
    def hypotheses(project_id: str, objective: str = "balanced",
                   _: str = Depends(auth)) -> list[dict]:
        return _guard(lambda: HypothesisService(get_ctx()).list_hypotheses(
            project_id, objective))

    @app.post("/projects/{project_id}/hypotheses/generate", status_code=202)
    def generate_hypotheses(project_id: str, _: str = Depends(auth)) -> dict:
        return _guard(lambda: HypothesisService(get_ctx()).generate(project_id))

    @app.get("/projects/{project_id}/reports")
    def reports(project_id: str, _: str = Depends(auth)) -> list[str]:
        return ReportService(get_ctx()).list_reports(project_id)

    @app.get("/projects/{project_id}/reports/{name}")
    def report_content(project_id: str, name: str,
                       _: str = Depends(auth)) -> dict:
        text = _guard(lambda: ReportService(get_ctx()).read_report(
            project_id, name))
        return {"name": name, "content": text}

    # ------------------------------------------------------ research/query
    @app.post("/projects/{project_id}/query")
    def query_memory(project_id: str, req: QueryRequest,
                     _: str = Depends(auth)) -> dict:
        return _guard(lambda: ResearchService(get_ctx()).ask(project_id, req))

    @app.post("/projects/{project_id}/search")
    def search_memory(project_id: str, req: QueryRequest,
                      _: str = Depends(auth)) -> list[dict]:
        return _guard(lambda: ResearchService(get_ctx()).search_memory(
            project_id, req))

    # ---------------------------------------------------------------- jobs
    @app.get("/jobs")
    def jobs(status: str = "", project_id: str = "",
             _: str = Depends(auth)) -> list[dict]:
        rows = get_ctx().platform_db.list_jobs(status=status,
                                               project_id=project_id)
        return [_job_dict(j) for j in rows]

    @app.post("/jobs", status_code=202)
    def create_job(project_id: str = "", type_: str = "deep_research",
                   _: str = Depends(auth)) -> JobRef:
        if type_ == "deep_research":
            job = _guard(lambda: ResearchService(get_ctx()).start(project_id))
            return JobRef(job_id=job.id, status=job.status)
        raise HTTPException(400, detail={"error": {
            "code": "UNSUPPORTED_JOB_TYPE", "message":
            f"job type {type_!r} not creatable via this endpoint"}})

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str, _: str = Depends(auth)) -> dict:
        j = get_ctx().platform_db.get_job(job_id)
        if j is None:
            raise HTTPException(404, detail={"error": {
                "code": "NOT_FOUND", "message": f"job {job_id} not found"}})
        out = _job_dict(j)
        out["tasks"] = [{"id": t.id, "type": t.type, "status": t.status,
                         "attempts": t.attempts,
                         "error_category": t.error_category}
                        for t in get_ctx().platform_db.tasks_for_job(job_id)]
        return out

    @app.post("/jobs/{job_id}/pause")
    def pause_job(job_id: str, _: str = Depends(auth)) -> dict:
        ok = _guard(lambda: get_ctx().scheduler.pause_job(job_id))
        if not ok:
            raise HTTPException(409, detail={"error": {
                "code": "NOT_PAUSABLE",
                "message": "job missing or already terminal"}})
        return {"pausing": True}

    @app.post("/jobs/{job_id}/resume")
    def resume_job(job_id: str, _: str = Depends(auth)) -> dict:
        j = _guard(lambda: get_ctx().scheduler.resume_job(job_id))
        if j is None:
            raise HTTPException(404, detail={"error": {
                "code": "NOT_FOUND", "message": f"job {job_id} not found"}})
        return {"job_id": j.id, "status": j.status}

    @app.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, _: str = Depends(auth)) -> dict:
        ok = _guard(lambda: get_ctx().scheduler.cancel_job(job_id))
        if not ok:
            raise HTTPException(409, detail={"error": {
                "code": "NOT_CANCELLABLE",
                "message": "job missing or already terminal"}})
        return {"cancelling": True}

    @app.post("/tasks/{task_id}/retry")
    def retry_task(task_id: str, _: str = Depends(auth)) -> dict:
        t = get_ctx().platform_db.requeue_task(task_id)
        if t is None:
            raise HTTPException(404, detail={"error": {
                "code": "NOT_FOUND", "message": f"task {task_id} not found"}})
        return {"task_id": t.id, "status": t.status}

    # --------------------------------------------------------- event stream
    @app.get("/events")
    def events(project_id: str = "", after_seq: int = 0,
               limit: int = Query(100, ge=1, le=500),
               _: str = Depends(auth)) -> list[dict]:
        return get_ctx().platform_db.events_for_project(
            project_id, limit=limit, after_seq=after_seq)

    @app.get("/events/stream")
    def event_stream(requested_project: str = "") -> StreamingResponse:
        """SSE stream of platform events (spec #108). Simple, no websockets."""
        bus = get_ctx().bus
        sub_id, q = bus.subscribe(None)

        def gen():
            yield ": connected\n\n"
            try:
                while True:
                    try:
                        ev = q.get(timeout=15)
                    except _queue.Empty:
                        yield ": keepalive\n\n"
                        continue
                    if requested_project and ev.project_id != requested_project:
                        continue
                    data = json.dumps(ev.to_dict(), default=str)
                    yield f"event: {ev.type}\ndata: {data}\n\n"
            finally:
                bus.unsubscribe(sub_id)

        return StreamingResponse(gen(), media_type="text/event-stream")

    # ---------------------------------------------------------- experiments
    @app.post("/projects/{project_id}/experiments", status_code=201)
    def register_experiment(project_id: str, spec: dict,
                            _: str = Depends(auth)) -> dict:
        return _guard(lambda: ExperimentService(get_ctx()).register(
            project_id, spec))

    @app.post("/projects/{project_id}/experiments/{exp_id}/execute", status_code=202)
    def execute_experiment(project_id: str, exp_id: str,
                           _: str = Depends(auth)) -> dict:
        return _guard(lambda: ExperimentService(get_ctx()).execute(
            project_id, exp_id))

    @app.post("/projects/{project_id}/experiments/{exp_id}/result")
    def add_experiment_result(project_id: str, exp_id: str,
                              body: dict, _: str = Depends(auth)) -> dict:
        return _guard(lambda: ExperimentService(get_ctx()).add_result(
            project_id, exp_id, observations=body.get("observations"),
            metrics=body.get("metrics"), raw_notes=body.get("raw_notes", "")))

    # -------------------------------------------------------------- errors
    @app.exception_handler(NotFoundError)
    async def _nf(_req, exc: NotFoundError):
        return _json_error(404, "NOT_FOUND", str(exc))

    @app.exception_handler(ConflictError)
    async def _conflict(_req, exc: ConflictError):
        return _json_error(409, "CONFLICT", str(exc))

    @app.exception_handler(ClassifiedError)
    async def _classified(_req, exc: ClassifiedError):
        code = {"NETWORK": "UPSTREAM_FAILURE", "AUTH": "UNAUTHORIZED"}.get(
            exc.category.value, "SERVICE_ERROR")
        status = {"AUTH": 403}.get(exc.category.value, 502)
        return _json_error(status, code, str(exc))

    return app


def _json_error(status: int, code: str, message: str):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message}})


def _guard(fn):
    """Normalize service exceptions into HTTP semantics."""
    try:
        return fn()
    except (NotFoundError, ConflictError, ClassifiedError):
        raise
    except FileNotFoundError as exc:
        raise NotFoundError("resource", str(exc)) from exc
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc


def _job_dict(j) -> dict:
    d = json.loads(j.model_dump_json())
    return {k: d[k] for k in ("id", "project_id", "type", "status", "priority",
                              "current_task", "progress", "completion_reason",
                              "error", "created_at", "started_at",
                              "completed_at")}


def make_auth_dependency(holder: dict):
    """Auth per spec #67: token required ONLY when host is non-local."""
    def dependency(request: Request) -> str:
        ctx = holder.get("ctx")
        host_cfg = ctx.cfg.platform.api.host if ctx else "127.0.0.1"
        external = host_cfg not in ("127.0.0.1", "localhost", "::1")
        if not external:
            return "local"
        token = ctx.cfg.platform.api.auth_token if ctx else ""
        provided = request.headers.get("X-API-Token", "")
        if not token or provided != token:
            raise HTTPException(401, detail={"error": {
                "code": "UNAUTHORIZED",
                "message": "valid X-API-Token required for external binding"}})
        return "token"

    return dependency


def health_report(ctx: ServiceContext) -> dict:
    """Health checks with degradation levels (spec #51/#52)."""
    checks: dict[str, dict] = {}

    # database
    try:
        ctx.platform_db.list_jobs(limit=1)
        checks["database"] = {"level": "healthy"}
    except Exception as exc:
        checks["database"] = {"level": "unavailable", "detail": str(exc)[:100]}

    # storage writable
    try:
        probe = Path_probe(ctx.data_dir)
        checks["storage"] = {"level": "healthy", "free_gb": probe}
    except Exception as exc:
        checks["storage"] = {"level": "degraded", "detail": str(exc)[:100]}

    # LLM provider (cheap reachability only — no completion)
    llm = ctx.cfg.models.reasoning
    if llm.provider in ("mock", "none"):
        checks["llm"] = {"level": "healthy", "provider": "mock",
                         "note": "deterministic fallback active"}
    else:
        checks["llm"] = {"level": "degraded", "provider": llm.provider,
                         "note": "not probed synchronously; see metrics"}

    # scheduler
    sched = getattr(ctx, "_scheduler", None)
    checks["scheduler"] = ({
        "level": "healthy",
        "threads": len(getattr(sched, "_threads", [])),
    } if sched and getattr(sched, "_threads", []) else
        {"level": "degraded", "note": "scheduler not started"})

    levels = [c["level"] for c in checks.values()]
    overall = ("unavailable" if "unavailable" in levels else
               "degraded" if "degraded" in levels else "healthy")
    return {"status": overall, "checks": checks}


def Path_probe(data_dir: str) -> float:
    import shutil
    usage = shutil.disk_usage(data_dir)
    return round(usage.free / 2**30, 1)
