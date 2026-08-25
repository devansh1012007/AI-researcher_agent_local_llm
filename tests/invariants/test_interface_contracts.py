"""INVARIANT-008: public interface contracts.

Every public API endpoint and every MCP tool must execute end-to-end
through the application-service seam with offline fakes. This is the
conformance net that would have caught BUG-03/BUG-06 at ship time.
"""
from __future__ import annotations

import json

import pytest


QUESTION = "Does retrieval augmented generation improve factuality of answers?"
STARTUP_Q = ("Find promising startup opportunities in AI bookkeeping "
             "software for Indian SMB retailers")


@pytest.fixture()
def client(platform_ctx):
    from fastapi.testclient import TestClient
    from research_engine.api.app import create_app
    with TestClient(create_app(platform_ctx)) as c:
        c.pid = c.post("/projects", json={"question": QUESTION}).json()["id"]
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

    def test_startup_surface(self, client):
        """Startup endpoints respond through the canonical service."""
        r = client.post("/startup/discover",
                        json={"question": STARTUP_Q, "create": False})
        # no startup project yet -> 404 is the CORRECT honest answer;
        # a 500/TypeError is not.
        assert r.status_code in (200, 404), r.text


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
        """Conformance: NO tool may crash with TypeError/AttributeError —
        domain errors (not-found) are acceptable outcomes; wiring bugs are
        not (this catches the BUG-06 class across the whole surface)."""
        from research_engine.mcp_server.server import build_tools
        srv = self._server(platform_ctx)
        pid = platform_ctx and self._mk_project(srv)
        schema_args = {
            "create_research_project": {"question": QUESTION},
            "start_research": {"project_id": pid},
            "get_research_status": {"project_id": pid},
            "pause_research": {"project_id": pid},
            "resume_research": {"project_id": pid},
            "cancel_research": {"project_id": pid},
            "get_job_status": {"job_id": "job_nope"},
            "get_research_report": {"project_id": pid, "name": "info.md"},
            "search_research_memory": {"project_id": pid, "query": "grounding"},
            "ask_research_memory": {"project_id": pid, "query": "grounding?"},
            "get_claim": {"claim_id": "clm_nope"},
            "trace_claim": {"claim_id": "clm_nope"},
            "get_evidence": {"evidence_id": "ev_nope"},
            "get_gaps": {"project_id": pid},
            "get_contradictions": {"project_id": pid},
            "list_hypotheses": {"project_id": pid},
            "generate_hypotheses": {"project_id": pid},
            "design_methodology": {"project_id": pid, "hypothesis_id": "hyp_nope"},
            "add_experiment_result": {"project_id": pid,
                                      "experiment_id": "exp_nope",
                                      "observations": ["o"]},
            "startup_get_market_map": {"project_id": pid},
            "startup_get_customer_segments": {"project_id": pid},
            "startup_get_competitors": {"project_id": pid},
            "startup_get_opportunities": {"project_id": pid},
            "startup_analyze_opportunity": {"opportunity_id": "opp_nope"},
            "startup_get_assumptions": {"project_id": pid},
            "startup_design_validation": {"project_id": pid},
            "startup_compare_opportunities": {"project_id": pid},
        }
        wired_failures = []
        for t in build_tools():
            name = t["name"]
            args = dict(schema_args.get(name) or {})
            resp = self._call(srv, name, args)
            err = resp.get("error") or {}
            result = resp.get("result") or {}
            text = (result.get("content") or [{}])[0].get("text", "")
            blob = json.dumps(resp)[:400]
            if err.get("code") == -32001:
                continue  # permission denial is a valid outcome elsewhere
            if "isError" in result and result.get("isError"):
                # tool-level honest failure: OK unless it's a wiring crash
                if any(k in text for k in ("TypeError", "AttributeError",
                                           "missing 1 required")):
                    wired_failures.append((name, text[:120]))
                continue
            if err.get("code") not in (None, -32001):
                msg = str(err.get("message", ""))
                if any(k in msg for k in ("TypeError", "AttributeError",
                                          "required positional")):
                    wired_failures.append((name, msg[:120]))
        assert not wired_failures, f"wiring crashes in tools: {wired_failures}"

    def _mk_project(self, srv) -> str:
        p = srv.projects.create(type("R", (), {"question": QUESTION,
                                               "mode": "academic"})())
        return p["id"]

    def test_design_methodology_tool_alive(self, platform_ctx):
        """P0-05/BUG-06 original repro shape: wrong-arity call must be gone."""
        from research_engine.mcp_server.server import McpServer
        srv = self._server(platform_ctx)
        pid = self._mk_project(srv)
        # create a hypothesis via canonical service then design methodology
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
