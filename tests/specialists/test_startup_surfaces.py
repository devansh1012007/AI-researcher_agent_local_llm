"""Startup specialist surface tests: REST API + MCP tools (spec #77/#78)."""
from __future__ import annotations

import json

import pytest


QUESTION = ("Find promising startup opportunities in AI bookkeeping "
            "software for Indian SMB retailers")

EVIDENCE = [
    "Retailers complain bookkeeping is manual and time-consuming, spending hours weekly in spreadsheets",
    "Shop owners report paying accountants 15000 rupees per month for basic bookkeeping",
    "Zoho Books pricing starts at $15 per month for small businesses",
    "New regulation mandates digital invoicing for retailers above turnover threshold from 2025",
]


@pytest.fixture()
def startup_api_project(platform_ctx):
    """A startup project with seeded evidence, created through the API."""
    from fastapi.testclient import TestClient
    from research_engine.api.app import create_app
    with TestClient(create_app(platform_ctx)) as c:
        r = c.post("/projects", json={"question": QUESTION, "mode": "startup"})
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        orch = _load_orch(platform_ctx, pid)
        from research_engine.models.evidence import Evidence
        from research_engine.models.research import Source
        s = Source(project_id=pid, url="https://f.example.com/1",
                   canonical_url="https://f.example.com/1",
                   domain="f.example.com", title="t")
        s.ensure_id()
        orch.repos.sources.save(s)
        for claim in EVIDENCE:
            e = Evidence(project_id=pid, claim_text=claim, quote=claim[:60],
                         source_id=s.id, source_tier=4, status="EXTRACTED")
            e.ensure_id()
            orch.repos.evidence.save(e)
        c.pid = pid
        yield c


@pytest.fixture()
def client(platform_ctx):
    from fastapi.testclient import TestClient
    from research_engine.api.app import create_app
    with TestClient(create_app(platform_ctx)) as c:
        yield c


def _load_orch(platform_ctx, pid):
    from research_engine.core.orchestrator import Orchestrator
    cfg = platform_ctx.cfg.model_copy(deep=True)
    cfg.storage.data_dir = platform_ctx.data_dir
    return Orchestrator.load(cfg, pid)


class TestStartupApi:
    def test_discover_validate_diligence_flow(self, startup_api_project):
        c = startup_api_project
        r = c.post("/startup/discover", json={"question": QUESTION,
                                              "create": False})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] >= 1
        assert body["patterns_seen"]

        v = c.post("/startup/validate", json={"project_id": c.pid})
        assert v.status_code == 200
        plans = v.json()["plans"]
        assert plans and plans[0]["tests_designed"]
        assert plans[0]["biggest_behavioral_uncertainty"] in (
            "willingness_to_pay", "frequency", None)

        d = c.get(f"/startup/opportunities/{body['opportunities'][0]['opportunity_id']}"
                  f"?project_id={c.pid}")
        assert d.status_code == 200
        dil = d.json()
        assert dil["readiness"]["level"] in ("NOT_READY", "RESEARCH_READY",
                                             "VALIDATION_READY", "PILOT_READY",
                                             "DECISION_READY")
        assert dil["recommendation"]["decision"]

    def test_market_map_and_segments_endpoints(self, startup_api_project):
        c = startup_api_project
        mm = c.get("/startup/market-map").json()
        assert "market_map" in mm and "segments" in mm
        segs = c.get("/startup/segments").json()
        assert "pain_points_ranked" in segs

    def test_startup_research_full_pipeline_endpoint(self, startup_api_project):
        c = startup_api_project
        r = c.post("/startup/research",
                   json={"question": QUESTION, "create": False,
                         "project_id": c.pid})
        assert r.status_code == 200
        body = r.json()
        assert "discovery" in body and "validation" in body and "diligence" in body
        # reports were written by the generator? at minimum diligence present
        assert body["diligence"].get("readiness")

    def test_no_startup_projects_404(self, client):
        r = client.get("/startup/competitors")
        assert r.status_code == 404


class TestStartupMcp:
    def _rpc(self, server, method, params=None, rid=1):
        req = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            req["params"] = params
        out = server.handle(req)
        return json.loads(out) if isinstance(out, str) else out

    def test_tool_roundtrip(self, platform_ctx):
        from research_engine.mcp_server.server import McpServer
        srv = McpServer(ctx=platform_ctx, permissions={"READ", "RESEARCH"},
                        stdin=open("/dev/null"), stdout=open("/dev/null", "w"))
        # create + seed via direct orchestrator (fast path)
        from research_engine.services.research_service import ProjectCreate
        p = srv.projects.create(ProjectCreate(question=QUESTION, mode="startup"))
        pid = p["id"]
        orch = _load_orch(platform_ctx, pid)
        from research_engine.models.evidence import Evidence
        from research_engine.models.research import Source
        s = Source(project_id=pid, url="https://f.example.com/1",
                   canonical_url="https://f.example.com/1",
                   domain="f.example.com", title="t")
        s.ensure_id()
        orch.repos.sources.save(s)
        for claim in EVIDENCE:
            e = Evidence(project_id=pid, claim_text=claim, quote=claim[:60],
                         source_id=s.id, source_tier=4, status="EXTRACTED")
            e.ensure_id()
            orch.repos.evidence.save(e)

        resp = self._rpc(srv, "tools/call",
                         {"name": "startup_get_market_map",
                          "arguments": {"project_id": pid}})
        assert resp["result"]["isError"] is False
        payload = json.loads(resp["result"]["content"][0]["text"])
        assert "market_map" in payload

        resp = self._rpc(srv, "tools/call",
                         {"name": "startup_discover_opportunities",
                          "arguments": {"project_id": pid}})
        payload = json.loads(resp["result"]["content"][0]["text"])
        assert payload["count"] >= 1

        resp = self._rpc(srv, "tools/call",
                         {"name": "startup_design_validation",
                          "arguments": {"project_id": pid}})
        payload = json.loads(resp["result"]["content"][0]["text"])
        assert payload["plans"][0]["assumptions_created"] > 0

        resp = self._rpc(srv, "tools/call",
                         {"name": "startup_get_assumptions",
                          "arguments": {"project_id": pid}})
        rows = json.loads(resp["result"]["content"][0]["text"])
        assert rows and rows[0]["priority"] >= rows[-1]["priority"]

    def test_read_only_client_cannot_run_research(self, platform_ctx):
        from research_engine.mcp_server.server import McpServer
        srv = McpServer(ctx=platform_ctx, permissions={"READ"},
                        stdin=open("/dev/null"), stdout=open("/dev/null", "w"))
        resp = self._rpc(srv, "tools/call",
                         {"name": "startup_research",
                          "arguments": {"question": QUESTION}})
        assert resp.get("error", {}).get("code") == -32001
