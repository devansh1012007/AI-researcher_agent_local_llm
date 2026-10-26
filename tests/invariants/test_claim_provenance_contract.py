"""MCP contract: `trace_claim` must work for a claim that EXISTS.

The conformance sweep in `test_interface_contracts.py` calls `trace_claim`
with `clm_nope` - a claim that does not exist - so the tool answered
"not found" and the wiring bug inside the REAL path never fired: the
reader used `claim.evidence_ids`, a field `Claim` does not have, so every
real claim raised AttributeError and the MCP tool answered "internal
error" (BUG-06 class).

This file calls the tool through the MCP boundary with a claim that
exists and asserts the SHAPE of the chain it returns: one entry per
evidence item, each carrying the `role` that says whether the evidence
supports or contradicts the claim.

Offline: the project is created through the MCP tool itself and the
claim/evidence rows are written to the project database the service
reads from.
"""
from __future__ import annotations

import json

QUESTION = "Does retrieval augmented generation improve factuality of answers?"


def _server(platform_ctx):
    from research_engine.mcp_server.server import McpServer

    return McpServer(ctx=platform_ctx, permissions={"READ", "RESEARCH", "WRITE"},
                      stdin=open("/dev/null"), stdout=open("/dev/null", "w"))


def _call(srv, name, args, rid=7):
    req = {"jsonrpc": "2.0", "id": rid,
           "method": "tools/call", "params": {"name": name, "arguments": args}}
    out = srv.handle(req)
    return json.loads(out) if isinstance(out, str) else out


def _project_with_a_claim(platform_ctx):
    """A project (created through the MCP service) holding one claim with
    one supporting evidence item."""
    from research_engine.core.orchestrator import Orchestrator
    from research_engine.models.evidence import Claim, Evidence

    srv = _server(platform_ctx)
    pid = srv.projects.create(
        type("R", (), {"question": QUESTION, "mode": "academic"})())["id"]
    orch = Orchestrator.load(platform_ctx.cfg, pid)
    ev = Evidence(project_id=pid, claim_text="Grounding improves factuality",
                  quote="Grounded answers cut hallucinations by 30 percent.",
                  source_url="https://example.org/paper", source_id="src_x",
                  document_id="doc_x")
    ev.ensure_id()
    orch.repos.evidence.save(ev)
    claim = Claim(project_id=pid, text="Grounding improves factuality")
    claim.ensure_id()
    claim.supported_by = [ev.id]
    orch.repos.claims.save(claim)
    return srv, pid, claim, ev


def test_trace_claim_returns_the_provenance_chain_of_a_real_claim(platform_ctx):
    srv, pid, claim, ev = _project_with_a_claim(platform_ctx)

    resp = _call(srv, "trace_claim", {"project_id": pid, "claim_id": claim.id})

    assert "error" not in resp, (
        f"the tool failed on a claim that exists: {json.dumps(resp)[:300]}")
    payload = json.loads(resp["result"]["content"][0]["text"])
    chain = payload["chain"]
    assert chain, (
        "the provenance chain of a claim with evidence is empty")
    assert all("role" in entry for entry in chain), (
        f"a chain entry carries no role, so the reader cannot tell what the "
        f"evidence does: {chain}")
    assert chain[0]["role"] == "supports"
    assert chain[0]["evidence_id"] == ev.id
    assert chain[0]["quote"] == "Grounded answers cut hallucinations by 30 percent."


def test_get_claim_works_for_a_real_claim(platform_ctx):
    """The sibling tool reads the same fields; it was broken the same way."""
    srv, pid, claim, _ev = _project_with_a_claim(platform_ctx)

    resp = _call(srv, "get_claim", {"project_id": pid, "claim_id": claim.id})

    assert "error" not in resp, (
        f"get_claim failed on a claim that exists: {json.dumps(resp)[:300]}")
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["claim"]["id"] == claim.id
    assert payload["evidence_count"] == 1
