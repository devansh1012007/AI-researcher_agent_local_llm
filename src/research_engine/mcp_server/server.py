"""MCP server: expose the research platform over the Model Context Protocol.

Thin adapter over application services (spec #27/#161) speaking JSON-RPC 2.0
on stdio — no external MCP SDK required. Implements:

    initialize / notifications/initialized
    tools/list, tools/call
    resources/list, resources/read
    ping

Security model (spec #30/#33):
  - every tool declares required_permission; PermissionEngine gates calls
  - long-running operations return job identity immediately (spec #31)
  - responses return summaries + ids, never the whole database (spec #32)
"""
from __future__ import annotations

import json
import sys
from typing import Any

from research_engine.platform.errors import ClassifiedError
from research_engine.security.permissions import (
    Permission, PermissionDeniedError, PermissionEngine,
)
from research_engine.services.context import ServiceContext
from research_engine.services.research_service import (
    ConflictError, NotFoundError, ProjectCreate, QueryRequest,
)

SERVER_INFO = {"name": "gar-research", "version": "4.0",
               "protocolVersion": "2024-11-05"}


# ------------------------------------------------------------------ tool specs
def build_tools() -> list[dict[str, Any]]:
    """Stable, high-value tools only (spec #28). Schemas are JSON Schema."""
    def t(name, desc, permission, schema):
        return {"name": name, "description": desc,
                "inputSchema": schema,
                "annotations": {"required_permission": permission}}

    return [
        t("create_research_project",
          "Create a research project from a question (mode: academic|startup)",
          Permission.RESEARCH,
          {"type": "object",
           "properties": {"question": {"type": "string"},
                          "mode": {"type": "string",
                                   "enum": ["academic", "startup"]}},
           "required": ["question"]}),
        t("start_research",
          "Queue a long-running deep research job; returns job id immediately",
          Permission.RESEARCH,
          {"type": "object",
           "properties": {"project_id": {"type": "string"},
                          "max_iterations": {"type": "integer"}},
           "required": ["project_id"]}),
        t("get_research_status",
          "Project state, budget, counts, and meaningful progress measures",
          Permission.READ,
          {"type": "object",
           "properties": {"project_id": {"type": "string"}},
           "required": ["project_id"]}),
        t("pause_research", "Pause running research for a project",
          Permission.RESEARCH,
          {"type": "object", "properties": {"project_id": {"type": "string"}},
           "required": ["project_id"]}),
        t("resume_research", "Resume paused research",
          Permission.RESEARCH,
          {"type": "object", "properties": {"project_id": {"type": "string"}},
           "required": ["project_id"]}),
        t("cancel_research", "Cancel running research (graceful)",
          Permission.RESEARCH,
          {"type": "object", "properties": {"project_id": {"type": "string"}},
           "required": ["project_id"]}),
        t("get_job_status", "Inspect a platform job incl. task states",
          Permission.READ,
          {"type": "object", "properties": {"job_id": {"type": "string"}},
           "required": ["job_id"]}),
        t("get_research_report", "Read a generated report by name",
          Permission.READ,
          {"type": "object",
           "properties": {"project_id": {"type": "string"},
                          "name": {"type": "string"}},
           "required": ["project_id", "name"]}),
        t("search_research_memory",
          "Hybrid retrieval over stored evidence chunks",
          Permission.READ,
          {"type": "object",
           "properties": {"project_id": {"type": "string"},
                          "query": {"type": "string"}, "top_k": {"type": "integer"}},
           "required": ["project_id", "query"]}),
        t("ask_research_memory",
          "Grounded Q&A with citation-backed answer or honest insufficiency",
          Permission.READ,
          {"type": "object",
           "properties": {"project_id": {"type": "string"},
                          "query": {"type": "string"}},
           "required": ["project_id", "query"]}),
        t("get_claim", "Claim detail with evidence provenance chain",
          Permission.READ,
          {"type": "object",
           "properties": {"project_id": {"type": "string"},
                          "claim_id": {"type": "string"}},
           "required": ["project_id", "claim_id"]}),
        t("trace_claim", "Full claim -> evidence -> source provenance chain",
          Permission.READ,
          {"type": "object",
           "properties": {"project_id": {"type": "string"},
                          "claim_id": {"type": "string"}},
           "required": ["project_id", "claim_id"]}),
        t("get_evidence", "Evidence item with its source",
          Permission.READ,
          {"type": "object",
           "properties": {"project_id": {"type": "string"},
                          "evidence_id": {"type": "string"}},
           "required": ["project_id", "evidence_id"]}),
        t("get_gaps", "Open research gaps sorted by importance",
          Permission.READ,
          {"type": "object", "properties": {"project_id": {"type": "string"}},
           "required": ["project_id"]}),
        t("get_contradictions", "Detected contradictions between claims",
          Permission.READ,
          {"type": "object", "properties": {"project_id": {"type": "string"}},
           "required": ["project_id"]}),
        t("list_hypotheses", "Ranked hypothesis portfolio",
          Permission.READ,
          {"type": "object",
           "properties": {"project_id": {"type": "string"},
                          "objective": {"type": "string", "enum":
                                        ["balanced", "novelty", "feasibility",
                                         "impact"]}},
           "required": ["project_id"]}),
        t("generate_hypotheses",
          "Generate competing hypotheses from top gaps/contradictions",
          Permission.RESEARCH,
          {"type": "object", "properties": {"project_id": {"type": "string"}},
           "required": ["project_id"]}),
        t("design_methodology",
          "Design tiered methodologies (cheap_fast/balanced/high_rigor)",
          Permission.RESEARCH,
          {"type": "object",
           "properties": {"project_id": {"type": "string"},
                          "hypothesis_id": {"type": "string"}},
           "required": ["project_id", "hypothesis_id"]}),
        t("add_experiment_result",
          "Ingest an experiment result; verdict vs pre-registered criteria",
          Permission.WRITE,
          {"type": "object",
           "properties": {"project_id": {"type": "string"},
                          "experiment_id": {"type": "string"},
                          "observations": {"type": "array",
                                           "items": {"type": "string"}},
                          "metrics": {"type": "object"},
                          "raw_notes": {"type": "string"}},
           "required": ["project_id", "experiment_id"]}),
    ]


RESOURCE_TEMPLATES = [
    {"uriTemplate": "research://project/{id}",
     "name": "Research project summary",
     "description": "State, counts, progress measures, top uncertainties"},
    {"uriTemplate": "research://project/{id}/report/{name}",
     "name": "Generated report", "description": "Markdown report content"},
    {"uriTemplate": "research://project/{id}/hypotheses",
     "name": "Hypothesis portfolio", "description": "Ranked hypotheses"},
    {"uriTemplate": "research://project/{id}/gaps",
     "name": "Research gaps", "description": "Open gaps by importance"},
]


class McpServer:
    def __init__(self, ctx: ServiceContext | None = None,
                 permissions: set[Permission] | None = None,
                 stdin=None, stdout=None):
        self.ctx = ctx
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.engine = PermissionEngine(permissions)
        self._services = {}

    # ------------------------------------------------------------- services
    def _ctx(self) -> ServiceContext:
        if self.ctx is None:
            from research_engine.services.context import get_context
            self.ctx = get_context()
        return self.ctx

    @property
    def projects(self):
        from research_engine.services.research_service import ProjectService
        return ProjectService(self._ctx())

    @property
    def research(self):
        from research_engine.services.research_service import ResearchService
        return ResearchService(self._ctx())

    @property
    def evidence(self):
        from research_engine.services.knowledge_service import EvidenceService
        return EvidenceService(self._ctx())

    @property
    def hypotheses(self):
        from research_engine.services.knowledge_service import HypothesisService
        return HypothesisService(self._ctx())

    @property
    def reports(self):
        from research_engine.services.knowledge_service import ReportService
        return ReportService(self._ctx())

    @property
    def experiments(self):
        from research_engine.services.knowledge_service import ExperimentService
        return ExperimentService(self._ctx())

    # ------------------------------------------------------------- protocol
    def handle(self, msg: dict) -> dict | None:
        method = msg.get("method", "")
        mid = msg.get("id")
        try:
            if method == "initialize":
                result = {"protocolVersion": SERVER_INFO["protocolVersion"],
                          "capabilities": {
                              "tools": {"listChanged": False},
                              "resources": {"subscribe": False}},
                          "serverInfo": {k: v for k, v in SERVER_INFO.items()
                                         if k != "protocolVersion"}}
            elif method == "notifications/initialized" or method.startswith(
                    "notifications/"):
                return None
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": build_tools()}
            elif method == "tools/call":
                result = self._call_tool(msg.get("params") or {})
            elif method == "resources/templates/list":
                result = {"resourceTemplates": RESOURCE_TEMPLATES}
            elif method == "resources/list":
                result = {"resources": self._list_resources()}
            elif method == "resources/read":
                result = self._read_resource((msg.get("params") or {}).get("uri", ""))
            else:
                return _rpc_error(mid, -32601, f"method not found: {method}")
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except (NotFoundError, ConflictError, ClassifiedError) as exc:
            return _rpc_error(mid, -32000, str(exc))
        except PermissionDeniedError as exc:
            return _rpc_error(mid, -32001, str(exc))
        except Exception as exc:  # noqa: BLE001 — protocol boundary
            return _rpc_error(mid, -32603, f"internal error: {exc}")

    # --------------------------------------------------------------- tools
    def _call_tool(self, params: dict) -> dict:
        name = params.get("name", "")
        args = params.get("arguments") or {}
        declared = next((t["annotations"]["required_permission"]
                         for t in build_tools() if t["name"] == name), None)
        self.engine.require(declared or Permission.ADMIN, f"tool:{name}")
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            raise NotFoundError("tool", name)
        content = handler(args)
        return {"content": [{"type": "text",
                             "text": json.dumps(content, default=str)}],
                "isError": False}

    def _tool_create_research_project(self, a: dict) -> dict:
        p = self.projects.create(ProjectCreate(question=a["question"],
                                               mode=a.get("mode", "academic")))
        # spec #32: summary + ids, not the full object
        return {"project_id": p["id"], "state": p["state"],
                "mode": p["mode"],
                "hint": "use start_research to begin deep research"}

    def _tool_start_research(self, a: dict) -> dict:
        from research_engine.services.research_service import ResearchStart
        req = ResearchStart(max_iterations=a.get("max_iterations"))
        job = self.research.start(a["project_id"], req)
        return {"job_id": job.id, "status": job.status,
                "note": "poll get_job_status for progress"}

    def _tool_get_research_status(self, a: dict) -> dict:
        return self.projects.status(a["project_id"])

    def _tool_pause_research(self, a: dict) -> dict:
        ok = self.projects.pause(a["project_id"])
        return {"paused": bool(ok)}

    def _tool_resume_research(self, a: dict) -> dict:
        return self.projects.resume(a["project_id"])

    def _tool_cancel_research(self, a: dict) -> dict:
        n = self.projects.cancel(a["project_id"])
        return {"cancelled_jobs": n}

    def _tool_get_job_status(self, a: dict) -> dict:
        j = self._ctx().platform_db.get_job(a["job_id"])
        if j is None:
            raise NotFoundError("job", a["job_id"])
        tasks = self._ctx().platform_db.tasks_for_job(j.id)
        return {"job_id": j.id, "status": j.status, "type": j.type,
                "progress": j.progress, "completion_reason": j.completion_reason,
                "tasks": [{"id": t.id, "status": t.status,
                           "attempts": t.attempts} for t in tasks]}

    def _tool_get_research_report(self, a: dict) -> dict:
        text = self.reports.read_report(a["project_id"], a["name"])
        return {"name": a["name"], "chars": len(text), "content": text[:20000]}

    def _tool_search_research_memory(self, a: dict) -> dict:
        hits = self.research.search_memory(
            a["project_id"], QueryRequest(query=a["query"],
                                          top_k=min(int(a.get("top_k", 8)), 50)))
        return {"results": hits[:10]}

    def _tool_ask_research_memory(self, a: dict) -> dict:
        return self.research.ask(a["project_id"],
                                 QueryRequest(query=a["query"]))

    def _tool_get_claim(self, a: dict) -> dict:
        evs = self.evidence.list_claims(a["project_id"], limit=10000)
        for c in evs["items"]:
            if c.get("id") == a["claim_id"]:
                chain = self.evidence.trace_claim(a["project_id"], c["id"])
                return {"claim": {k: c.get(k) for k in
                                  ("id", "text", "confidence", "tier")},
                        "evidence_count": len(chain)}
        raise NotFoundError("claim", a["claim_id"])

    def _tool_trace_claim(self, a: dict) -> dict:
        return {"chain": self.evidence.trace_claim(a["project_id"],
                                                   a["claim_id"])}

    def _tool_get_evidence(self, a: dict) -> dict:
        e = self.evidence.get_evidence(a["project_id"], a["evidence_id"])
        return {"id": e["id"], "quote": e["quote"], "claim_text": e.get("claim_text"),
                "tier": e.get("source_tier"), "url": e.get("source_url"),
                "source": (e.get("source") or {}).get("title", "")}

    def _tool_get_gaps(self, a: dict) -> dict:
        page = self.evidence.list_gaps(a["project_id"], limit=20)
        return {"gaps": [{"id": g["id"], "importance": g["importance"],
                          "description": g["description"][:160]}
                         for g in page["items"]]}

    def _tool_get_contradictions(self, a: dict) -> dict:
        cons = self.evidence.contradictions(a["project_id"])
        return {"contradictions": [{"id": c.get("id"),
                                    "explanation": (c.get("explanation")
                                                    or "")[:200]}
                                   for c in cons[:20]]}

    def _tool_list_hypotheses(self, a: dict) -> dict:
        hyps = self.hypotheses.list_hypotheses(a["project_id"],
                                               a.get("objective", "balanced"))
        return {"hypotheses": [{"id": h["id"], "title": h["title"],
                                "score": h.get("rank_score"),
                                "confidence": h["confidence"],
                                "status": h["status"]} for h in hyps[:15]]}

    def _tool_generate_hypotheses(self, a: dict) -> dict:
        summary = self.hypotheses.generate(a["project_id"])
        return {"generated": len(summary.get("generated", [])),
                "top": [{"id": r.get("id"), "score": round(r.get("score", 0), 3)}
                        for r in summary.get("ranked", [])[:5]]}

    def _tool_design_methodology(self, a: dict) -> dict:
        orch = _load_orch(self._ctx(), a["project_id"])
        rr = _rrepos_of(orch)
        from research_engine.reasoning.methodology_designer import MethodologyDesigner
        h = rr.hypotheses.get(a["hypothesis_id"])
        if h is None:
            raise NotFoundError("hypothesis", a["hypothesis_id"])
        designs = MethodologyDesigner(orch.router.reasoning, orch.repos).design(h)
        out = []
        for d in designs:
            m = rr.methodologies.save(d)
            out.append({"methodology_id": d.id, "tier": d.tier,
                        "success_criteria": d.success_criteria})
        return {"methodologies": out}

    def _tool_add_experiment_result(self, a: dict) -> dict:
        outcome = self.experiments.add_result(
            a["project_id"], a["experiment_id"],
            observations=a.get("observations"),
            metrics=a.get("metrics"), raw_notes=a.get("raw_notes", ""))
        return outcome

    # ----------------------------------------------------------- resources
    def _list_resources(self) -> list[dict]:
        out = []
        for p in self.projects.list_projects()[:50]:
            pid = p.get("id", "")
            out.append({"uri": f"research://project/{pid}",
                        "name": (p.get("question") or "")[:80],
                        "mimeType": "application/json"})
        return out

    def _read_resource(self, uri: str) -> dict:
        prefix = "research://project/"
        if not uri.startswith(prefix):
            raise NotFoundError("resource", uri)
        rest = uri[len(prefix):]
        parts = [x for x in rest.split("/") if x]
        pid = parts[0] if parts else ""
        if len(parts) >= 2 and parts[1] == "report":
            text = self.reports.read_report(pid, parts[2])
            return {"contents": [{"uri": uri, "mimeType": "text/markdown",
                                  "text": text}]}
        if len(parts) >= 2 and parts[1] == "hypotheses":
            body = self.hypotheses.list_hypotheses(pid)[:10]
            return {"contents": [{"uri": uri, "mimeType": "application/json",
                                  "text": json.dumps(body, default=str)}]}
        if len(parts) >= 2 and parts[1] == "gaps":
            page = self.evidence.list_gaps(pid, limit=25)
            return {"contents": [{"uri": uri, "mimeType": "application/json",
                                  "text": json.dumps(page["items"][:25])}]}
        summary = self.projects.status(pid)
        return {"contents": [{"uri": uri, "mimeType": "application/json",
                              "text": json.dumps(summary, default=str)}]}

    # ---------------------------------------------------------------- io
    def serve_forever(self) -> None:  # pragma: no cover - stdio loop
        for line in self.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                resp = _rpc_error(None, -32700, "parse error")
            else:
                resp = self.handle(msg)
            if resp is not None:
                self.stdout.write(json.dumps(resp, default=str) + "\n")
                self.stdout.flush()


def _rpc_error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": code, "message": message}}


def _load_orch(ctx, project_id):
    from research_engine.core.orchestrator import Orchestrator
    try:
        return Orchestrator.load(ctx.cfg, project_id)
    except FileNotFoundError as exc:
        raise NotFoundError("project", project_id) from exc


def _rrepos_of(orch):
    from research_engine.storage.reasoning_repos import ReasoningRepos
    if not hasattr(orch, "_rrepos"):
        orch._rrepos = ReasoningRepos(orch.db)
    return orch._rrepos
