"""MCP protocol + security tests (spec #27-33/#92/#144):
tool discovery, schema, resources, long-running semantics, permissions,
state consistency, injection resistance at the interface boundary."""
from __future__ import annotations

import json

import pytest

from research_engine.mcp_server.server import McpServer
from research_engine.security.permissions import Permission


@pytest.fixture()
def server(platform_ctx):
    return McpServer(platform_ctx,
                     permissions={Permission.READ, Permission.RESEARCH,
                                  Permission.WRITE})


def _call(srv, name, args, mid=1):
    return srv.handle({"jsonrpc": "2.0", "id": mid,
                       "method": "tools/call",
                       "params": {"name": name, "arguments": args}})


class TestProtocol:
    def test_initialize_handshake(self, server):
        r = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert r["result"]["protocolVersion"] == "2024-11-05"
        assert "tools" in r["result"]["capabilities"]

    def test_notifications_yield_no_response(self, server):
        assert server.handle({"jsonrpc": "2.0", "method":
                              "notifications/initialized"}) is None

    def test_unknown_method(self, server):
        r = server.handle({"jsonrpc": "2.0", "id": 9, "method": "x/y"})
        assert r["error"]["code"] == -32601

    def test_tool_discovery_and_schemas(self, server):
        r = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = {t["name"]: t for t in r["result"]["tools"]}
        for expected in ("create_research_project", "start_research",
                         "get_research_status", "pause_research",
                         "resume_research", "cancel_research",
                         "get_research_report", "search_research_memory",
                         "get_claim", "trace_claim", "get_evidence",
                         "get_gaps", "list_hypotheses",
                         "add_experiment_result"):
            assert expected in tools, expected
            t = tools[expected]
            assert t["inputSchema"]["type"] == "object"
            assert "required_permission" in t["annotations"]
        # every tool declares a permission (spec #33)
        from research_engine.security.permissions import Permission as P
        assert all(t["annotations"]["required_permission"] in list(P)
                   for t in tools.values())


class TestToolSemantics:
    def test_create_then_status(self, server):
        r = _call(server, "create_research_project",
                  {"question": "Can small local models do multi-hop reasoning reliably?"})
        out = json.loads(r["result"]["content"][0]["text"])
        pid = out["project_id"]
        st = json.loads(_call(server, "get_research_status",
                              {"project_id": pid})["result"]["content"][0]["text"])
        assert st["id"] == pid and "progress" in st

    def test_start_returns_job_identity_not_block(self, server):
        """Long-running research must NOT hold the tool call open (#31)."""
        pid = json.loads(_call(
            server, "create_research_project",
            {"question": "Are retrieval indexes stable under domain shift?"}
        )["result"]["content"][0]["text"])["project_id"]
        r = _call(server, "start_research", {"project_id": pid})
        out = json.loads(r["result"]["content"][0]["text"])
        assert out["status"] in ("QUEUED", "RUNNING")
        assert "job_id" in out
        jr = _call(server, "get_job_status", {"job_id": out["job_id"]})
        assert "status" in json.loads(jr["result"]["content"][0]["text"])

    def test_missing_resources_are_errors(self, server):
        r = _call(server, "get_evidence",
                  {"project_id": "proj_x", "evidence_id": "ev_nope"})
        assert "error" in r

    def test_unknown_tool(self, server):
        r = _call(server, "delete_everything", {})
        assert "error" in r


class TestPermissions:
    def test_read_only_client_cannot_start_research(self, platform_ctx):
        ro = McpServer(platform_ctx)   # default: READ only
        r = _call(ro, "start_research", {"project_id": "proj_x"})
        assert r["error"]["code"] == -32001
        assert "permission denied" in r["error"]["message"]

    def test_write_requires_explicit_grant(self, platform_ctx):
        ro = McpServer(platform_ctx, permissions={Permission.READ,
                                                  Permission.RESEARCH})
        r = _call(ro, "add_experiment_result",
                  {"project_id": "p", "experiment_id": "e"})
        assert r["error"]["code"] == -32001

    def test_admin_passes_everything(self, platform_ctx):
        adm = McpServer(platform_ctx, permissions={Permission.ADMIN})
        r = _call(adm, "create_research_project",
                  {"question": "admin can create projects fine"})
        assert "error" not in r


class TestResources:
    def test_resource_roundtrip(self, server):
        pid = json.loads(_call(
            server, "create_research_project",
            {"question": "resource roundtrip project question here"}
        )["result"]["content"][0]["text"])["project_id"]
        listed = server.handle({"jsonrpc": "2.0", "id": 3,
                                "method": "resources/list"})
        assert any(pid in r["uri"] for r in listed["result"]["resources"])
        read = server.handle({"jsonrpc": "2.0", "id": 4,
                              "method": "resources/read",
                              "params": {"uri": f"research://project/{pid}"}})
        body = json.loads(read["result"]["contents"][0]["text"])
        assert body["id"] == pid
        gaps = server.handle({"jsonrpc": "2.0", "id": 5,
                              "method": "resources/read",
                              "params": {"uri": f"research://project/{pid}/gaps"}})
        assert gaps["result"]["contents"][0]["uri"].endswith("/gaps")

    def test_bad_uri(self, server):
        r = server.handle({"jsonrpc": "2.0", "id": 6,
                           "method": "resources/read",
                           "params": {"uri": "file:///etc/passwd"}})
        assert "error" in r   # no arbitrary file access via resources (#30)
