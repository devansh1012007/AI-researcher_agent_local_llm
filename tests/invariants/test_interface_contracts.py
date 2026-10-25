"""INVARIANT-008: public interface contracts.

Every public API endpoint and every MCP tool must execute end-to-end
through the application-service seam with offline fakes, and every
registered API route and MCP tool must be documented in docs/api.md and
docs/mcp.md (P2-1 / 4.2).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
QUESTION = "Does retrieval augmented generation improve factuality of answers?"
STARTUP_Q = ("Find promising startup opportunities in AI bookkeeping "
             "software for Indian SMB retailers")


@pytest.fixture()
def client(platform_ctx):
    from fastapi.testclient import TestClient
    from research_engine.api.app import create_app
    with TestClient(create_app(platform_ctx)) as c:
        c.pid = c.post("/projects", json={"question": QUESTION}).json()["id"]
        c.startup_pid = c.post(
            "/projects", json={"question": STARTUP_Q, "mode": "startup"}
        ).json()["id"]
        yield c


class TestApiContracts:
    def test_ask_endpoint_alive(self, client):
        """P0-05 original repro: this used to TypeError 100% of the time."""
        r = client.post(f"/projects/{client.pid}/query",
                        json={"query": "does grounding help?", "top_k": 3})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "answer" in body and "confidence" in body

    def test_core_project_lifecycle(self, client):
        got = client.get(f"/projects/{client.pid}")
        assert got.status_code == 200
        assert any(p["id"] == client.pid for p in client.get("/projects").json())
        st = client.get(f"/projects/{client.pid}/status")
        assert st.status_code == 200

    def test_knowledge_reads(self, client):
        for path in ("/evidence", "/claims", "/gaps", "/contradictions",
                     "/hypotheses", "/reports"):
            r = client.get(f"/projects/{client.pid}{path}")
            assert r.status_code == 200, f"{path}: {r.text[:120]}"

    def test_jobs_endpoints(self, client):
        assert client.get("/jobs").status_code == 200
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200
        assert client.get("/info").status_code == 200

    def test_startup_surface(self, client):
        """Startup endpoints respond through the canonical service."""
        r = client.post("/startup/discover",
                        json={"question": STARTUP_Q, "create": False})
        assert r.status_code in (200, 404), r.text

    def test_every_registered_fastapi_route_executes_without_500(self, client):
        """P2-1: dynamically discover every FastAPI route and invoke it."""
        app = client.app
        del_pid = client.post(
            "/projects", json={"question": "Temporary project for delete route test"}
        ).json()["id"]
        pid = client.pid
        spid = client.startup_pid

        route_calls = {
            ("GET", "/health"): lambda: client.get("/health"),
            ("GET", "/ready"): lambda: client.get("/ready"),
            ("GET", "/info"): lambda: client.get("/info"),
            ("POST", "/projects"): lambda: client.post(
                "/projects", json={"question": "Another test question for route check"}
            ),
            ("GET", "/projects"): lambda: client.get("/projects"),
            ("GET", "/projects/{project_id}"): lambda: client.get(f"/projects/{pid}"),
            ("DELETE", "/projects/{project_id}"): lambda: client.delete(f"/projects/{del_pid}"),
            ("GET", "/projects/{project_id}/status"): lambda: client.get(f"/projects/{pid}/status"),
            ("POST", "/projects/{project_id}/run"): lambda: client.post(
                f"/projects/{pid}/run", json={"max_iterations": 1}
            ),
            ("POST", "/projects/{project_id}/pause"): lambda: client.post(f"/projects/{pid}/pause"),
            ("POST", "/projects/{project_id}/resume"): lambda: client.post(f"/projects/{pid}/resume"),
            ("POST", "/projects/{project_id}/cancel"): lambda: client.post(f"/projects/{pid}/cancel"),
            ("POST", "/projects/{project_id}/query"): lambda: client.post(
                f"/projects/{pid}/query", json={"query": "grounding", "top_k": 2}
            ),
            ("POST", "/projects/{project_id}/search"): lambda: client.post(
                f"/projects/{pid}/search", json={"query": "grounding", "top_k": 2}
            ),
            ("GET", "/projects/{project_id}/evidence"): lambda: client.get(f"/projects/{pid}/evidence"),
            ("GET", "/projects/{project_id}/claims"): lambda: client.get(f"/projects/{pid}/claims"),
            ("GET", "/projects/{project_id}/gaps"): lambda: client.get(f"/projects/{pid}/gaps"),
            ("GET", "/projects/{project_id}/contradictions"): lambda: client.get(
                f"/projects/{pid}/contradictions"
            ),
            ("GET", "/projects/{project_id}/hypotheses"): lambda: client.get(
                f"/projects/{pid}/hypotheses"
            ),
            ("POST", "/projects/{project_id}/hypotheses/generate"): lambda: client.post(
                f"/projects/{pid}/hypotheses/generate"
            ),
            ("GET", "/projects/{project_id}/reports"): lambda: client.get(f"/projects/{pid}/reports"),
            ("GET", "/projects/{project_id}/reports/{name}"): lambda: client.get(
                f"/projects/{pid}/reports/info.md"
            ),
            ("POST", "/projects/{project_id}/review/decisions"): lambda: client.post(
                f"/projects/{pid}/review/decisions",
                json={"target_kind": "claim", "target_id": "clm_nope", "verdict": "APPROVED"},
            ),
            ("GET", "/jobs"): lambda: client.get("/jobs"),
            ("POST", "/jobs"): lambda: client.post(
                f"/jobs?type_=deep_research&project_id={pid}"
            ),
            ("GET", "/jobs/{job_id}"): lambda: client.get("/jobs/job_nope"),
            ("POST", "/jobs/{job_id}/pause"): lambda: client.post("/jobs/job_nope/pause"),
            ("POST", "/jobs/{job_id}/resume"): lambda: client.post("/jobs/job_nope/resume"),
            ("POST", "/jobs/{job_id}/cancel"): lambda: client.post("/jobs/job_nope/cancel"),
            ("POST", "/tasks/{task_id}/retry"): lambda: client.post("/tasks/tsk_nope/retry"),
            ("GET", "/events"): lambda: client.get("/events"),
            ("GET", "/events/stream"): lambda: None,
            ("POST", "/projects/{project_id}/experiments"): lambda: client.post(
                f"/projects/{pid}/experiments",
                json={"hypothesis_id": "hyp_nope", "methodology_id": "mth_nope"},
            ),
            ("POST", "/projects/{project_id}/experiments/{exp_id}/execute"): lambda: client.post(
                f"/projects/{pid}/experiments/exp_nope/execute",
                json={"code": "print(1)"},
            ),
            ("POST", "/projects/{project_id}/experiments/{exp_id}/result"): lambda: client.post(
                f"/projects/{pid}/experiments/exp_nope/result",
                json={"observations": ["obs"], "metrics": {}},
            ),
            ("POST", "/startup/research"): lambda: client.post(
                "/startup/research", json={"question": STARTUP_Q, "project_id": spid}
            ),
            ("POST", "/startup/discover"): lambda: client.post(
                "/startup/discover", json={"question": STARTUP_Q, "project_id": spid}
            ),
            ("GET", "/startup/market-map"): lambda: client.get(
                f"/startup/market-map?project_id={spid}"
            ),
            ("GET", "/startup/segments"): lambda: client.get(
                f"/startup/segments?project_id={spid}"
            ),
            ("GET", "/startup/competitors"): lambda: client.get(
                f"/startup/competitors?project_id={spid}"
            ),
            ("GET", "/startup/opportunities/{opportunity_id}"): lambda: client.get(
                f"/startup/opportunities/opp_nope?project_id={spid}"
            ),
            ("POST", "/startup/validate"): lambda: client.post(
                "/startup/validate", json={"project_id": spid}
            ),
            ("POST", "/startup/compare"): lambda: client.post(
                "/startup/compare", json={"project_id": spid}
            ),
        }

        discovered = set()
        for r in app.routes:
            path = getattr(r, "path", "")
            if path in ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"):
                continue
            for m in (getattr(r, "methods", None) or []):
                if m != "HEAD":
                    discovered.add((m, path))

        missing_from_table = discovered - set(route_calls.keys())
        assert not missing_from_table, f"Unmapped FastAPI routes: {sorted(missing_from_table)}"

        unexpected_500s = []
        for (method, path), caller in sorted(route_calls.items()):
            if (method, path) == ("GET", "/events/stream"):
                continue
            resp = caller()
            if resp.status_code >= 500:
                unexpected_500s.append((method, path, resp.status_code, resp.text[:200]))
            elif resp.status_code >= 400:
                body = resp.json()
                assert "error" in body and "code" in body["error"], (
                    f"{method} {path} returned non-standard error: {body}"
                )
        assert not unexpected_500s, f"Routes crashed with 5xx: {unexpected_500s}"

    def test_api_docs_cover_every_registered_route(self, client):
        """P2-1: docs/api.md must mention every registered API route."""
        doc_text = (ROOT / "docs" / "api.md").read_text(encoding="utf-8")
        missing = []
        for r in client.app.routes:
            path = getattr(r, "path", "")
            if path in ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"):
                continue
            for m in (getattr(r, "methods", None) or []):
                if m == "HEAD":
                    continue
                sig = f"{m} {path}"
                if sig not in doc_text:
                    missing.append(sig)
        assert not missing, f"Routes missing from docs/api.md: {missing}"


class TestMcpContracts:
    def _server(self, platform_ctx):
        from research_engine.mcp_server.server import McpServer
        return McpServer(ctx=platform_ctx, permissions={"READ", "RESEARCH", "WRITE"},
                         stdin=open("/dev/null"), stdout=open("/dev/null", "w"))

    def _call(self, srv, name, args, rid=7):
        req = {"jsonrpc": "2.0", "id": rid,
               "method": "tools/call", "params": {"name": name, "arguments": args}}
        out = srv.handle(req)
        out = json.loads(out) if isinstance(out, str) else out
        return out

    def test_every_tool_executes_or_fails_honestly(self, platform_ctx):
        """Conformance: every tool in build_tools() has explicit test args and
        executes without TypeError/AttributeError wiring bugs."""
        from research_engine.mcp_server.server import build_tools
        srv = self._server(platform_ctx)
        pid = self._mk_project(srv, mode="academic", question=QUESTION)
        spid = self._mk_project(srv, mode="startup", question=STARTUP_Q)
        schema_args = {
            "create_research_project": {"question": QUESTION, "mode": "academic"},
            "start_research": {"project_id": pid},
            "get_research_status": {"project_id": pid},
            "pause_research": {"project_id": pid},
            "resume_research": {"project_id": pid},
            "cancel_research": {"project_id": pid},
            "get_job_status": {"job_id": "job_nope"},
            "get_research_report": {"project_id": pid, "name": "info.md"},
            "search_research_memory": {"project_id": pid, "query": "grounding"},
            "ask_research_memory": {"project_id": pid, "query": "grounding?"},
            "get_claim": {"project_id": pid, "claim_id": "clm_nope"},
            "trace_claim": {"project_id": pid, "claim_id": "clm_nope"},
            "get_evidence": {"project_id": pid, "evidence_id": "ev_nope"},
            "get_gaps": {"project_id": pid},
            "get_contradictions": {"project_id": pid},
            "list_hypotheses": {"project_id": pid},
            "generate_hypotheses": {"project_id": pid},
            "design_methodology": {"project_id": pid, "hypothesis_id": "hyp_nope"},
            "add_experiment_result": {"project_id": pid,
                                      "experiment_id": "exp_nope",
                                      "observations": ["o"]},
            "record_review_decision": {"project_id": pid,
                                       "target_kind": "claim",
                                       "target_id": "clm_nope",
                                       "verdict": "APPROVED",
                                       "note": "test"},
            "startup_research": {"question": STARTUP_Q, "project_id": spid},
            "startup_discover_opportunities": {"question": STARTUP_Q, "project_id": spid},
            "startup_get_market_map": {"project_id": spid},
            "startup_get_customer_segments": {"project_id": spid},
            "startup_get_competitors": {"project_id": spid},
            "startup_get_opportunities": {"project_id": spid},
            "startup_analyze_opportunity": {"opportunity_id": "opp_nope", "project_id": spid},
            "startup_get_assumptions": {"project_id": spid},
            "startup_design_validation": {"project_id": spid},
            "startup_compare_opportunities": {"project_id": spid},
        }
        tools = build_tools()
        tool_names = {t["name"] for t in tools}
        assert tool_names == set(schema_args.keys()), (
            f"Tool table mismatch: missing={tool_names - set(schema_args.keys())}, "
            f"extra={set(schema_args.keys()) - tool_names}"
        )
        wired_failures = []
        for t in tools:
            name = t["name"]
            args = dict(schema_args[name])
            resp = self._call(srv, name, args)
            err = resp.get("error") or {}
            result = resp.get("result") or {}
            text = (result.get("content") or [{}])[0].get("text", "")
            if err.get("code") == -32001:
                continue
            if "isError" in result and result.get("isError"):
                if any(k in text for k in ("TypeError", "AttributeError",
                                           "missing 1 required")):
                    wired_failures.append((name, text[:120]))
                continue
            if err.get("code") not in (None, -32001):
                msg = str(err.get("message", ""))
                if any(k in msg for k in ("TypeError", "AttributeError",
                                          "required positional", "internal error")):
                    wired_failures.append((name, msg[:120]))
        assert not wired_failures, f"wiring crashes in tools: {wired_failures}"

    def test_mcp_docs_cover_every_registered_tool(self):
        """P2-1: docs/mcp.md must mention every tool in build_tools()."""
        from research_engine.mcp_server.server import build_tools
        doc_text = (ROOT / "docs" / "mcp.md").read_text(encoding="utf-8")
        missing = [t["name"] for t in build_tools() if t["name"] not in doc_text]
        assert not missing, f"MCP tools missing from docs/mcp.md: {missing}"

    def test_trace_claim_and_record_review_decision_end_to_end(self, platform_ctx):
        """4.2: verify trace_claim returns role on chain entries and
        record_review_decision works end-to-end via MCP."""
        from research_engine.core.orchestrator import Orchestrator
        from research_engine.models.evidence import Claim, Evidence
        from research_engine.models.research import Source

        srv = self._server(platform_ctx)
        pid = self._mk_project(srv, mode="academic", question=QUESTION)
        orch = Orchestrator.load(platform_ctx.cfg, pid)
        src = Source(project_id=pid, url="https://example.org/p",
                     canonical_url="example.org/p", title="Paper")
        src.ensure_id()
        orch.repos.sources.save(src)
        ev_sup = Evidence(project_id=pid, source_id=src.id,
                          claim_text="RAG improves factuality.",
                          quote="RAG improves factuality.",
                          source_url=src.url)
        ev_sup.ensure_id()
        orch.repos.evidence.save(ev_sup)
        ev_con = Evidence(project_id=pid, source_id=src.id,
                          claim_text="RAG does not always help.",
                          quote="RAG does not always help.",
                          source_url=src.url)
        ev_con.ensure_id()
        orch.repos.evidence.save(ev_con)
        clm = Claim(project_id=pid, text="RAG improves factuality.",
                    supported_by=[ev_sup.id], contradicted_by=[ev_con.id],
                    confidence=0.8)
        clm.ensure_id()
        orch.repos.claims.save(clm)

        trace_resp = self._call(srv, "trace_claim",
                                {"project_id": pid, "claim_id": clm.id})
        assert "error" not in trace_resp, trace_resp
        chain = json.loads(trace_resp["result"]["content"][0]["text"])["chain"]
        roles = {item["evidence_id"]: item["role"] for item in chain}
        assert roles == {ev_sup.id: "supports", ev_con.id: "contradicts"}

        rev_resp = self._call(srv, "record_review_decision",
                              {"project_id": pid, "target_kind": "claim",
                               "target_id": clm.id, "verdict": "APPROVED",
                               "note": "verified by analyst",
                               "reviewer_label": "alice"})
        assert "error" not in rev_resp, rev_resp
        decision = json.loads(rev_resp["result"]["content"][0]["text"])
        assert decision["verdict"] == "APPROVED"
        assert decision["actor_kind"] == "unverified_label"

    def _mk_project(self, srv, mode="academic", question=QUESTION) -> str:
        p = srv.projects.create(type("R", (), {"question": question,
                                               "mode": mode})())
        return p["id"]

    def test_design_methodology_tool_alive(self, platform_ctx):
        """P0-05/BUG-06 original repro shape: wrong-arity call must be gone."""
        srv = self._server(platform_ctx)
        pid = self._mk_project(srv)
        hyps = srv.knowledge.hypotheses.generate(pid)
        assert hyps, "hypothesis generation should produce hypotheses"
        hyp_id = hyps["generated"][0]["id"] if hyps.get("generated") else None
        if hyp_id is None:
            pytest.skip("no hypotheses generated offline")
        resp = self._call(srv, "design_methodology",
                          {"project_id": pid, "hypothesis_id": hyp_id})
        assert "error" not in resp or resp["error"] is None, str(resp)[:200]
        payload = json.loads(resp["result"]["content"][0]["text"])
        assert isinstance(payload.get("methodologies"), list)

    def test_ask_tool_alive(self, platform_ctx):
        srv = self._server(platform_ctx)
        pid = self._mk_project(srv)
        resp = self._call(srv, "ask_research_memory",
                          {"project_id": pid, "query": "grounding?"})
        assert "TypeError" not in json.dumps(resp)
