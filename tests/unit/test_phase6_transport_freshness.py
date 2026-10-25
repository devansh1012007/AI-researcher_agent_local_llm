"""Phase 6 tests: 6.1 MCP 1 MiB max line limit, 6.2 freshness_summary & ReportRepo wiring."""
from __future__ import annotations

import io
import json
from research_engine.mcp_server.server import McpServer
from research_engine.specialists.startup.kb import MarketKnowledgeBase
from research_engine.specialists.startup.models import CompetitorProfile, Market, PricingPlan


def test_mcp_serve_forever_rejects_oversized_line_and_continues(platform_ctx):
    """Phase 6.1: lines > 1 MiB return -32600 Invalid Request without killing the loop."""
    oversized = '{"jsonrpc":"2.0","id":1,"method":"ping","pad":"' + ("x" * (1024 * 1024 + 64)) + '"}\n'
    valid_ping = '{"jsonrpc":"2.0","id":2,"method":"ping"}\n'
    stdin = io.StringIO(oversized + valid_ping)
    stdout = io.StringIO()

    srv = McpServer(ctx=platform_ctx, stdin=stdin, stdout=stdout)
    srv.serve_forever()

    lines = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert len(lines) == 2
    assert lines[0]["error"]["code"] == -32600
    assert "1 MiB" in lines[0]["error"]["message"]
    assert lines[1]["id"] == 2
    assert lines[1]["result"] == {}


def test_kb_freshness_summary_uses_competitor_and_pricing_observed_at(tmp_path):
    """Phase 6.2: freshness_summary computes competitor and pricing freshness from observed_at."""
    kb = MarketKnowledgeBase(tmp_path)
    mkt = Market(project_id="proj_1", name="Retail Bookkeeping", market_slug="retail-bookkeeping")
    comp_fresh = CompetitorProfile(project_id="proj_1", name="FreshCo", observed_at="2026-10-01")
    comp_stale = CompetitorProfile(project_id="proj_1", name="StaleCo", observed_at="2023-01-01")
    plan_fresh = PricingPlan(project_id="proj_1", competitor_name="FreshCo", price_raw="$20/mo",
                             observed_at="2026-10-15")
    plan_stale = PricingPlan(project_id="proj_1", competitor_name="StaleCo", price_raw="$99/mo",
                             observed_at="2024-01-01")

    kb.remember_market(mkt, competitors=[comp_fresh, comp_stale],
                       pricing_plans=[plan_fresh, plan_stale])
    entry = kb.lookup("retail-bookkeeping")
    summary = kb.freshness_summary(entry, today="2026-10-25")

    comp_states = {c["name"]: c["state"] for c in summary["competitors"]}
    assert comp_states["FreshCo"] == "fresh"
    assert comp_states["StaleCo"] == "stale"

    price_states = {p["raw"]: p["state"] for p in summary["pricing"]}
    assert price_states["$20/mo"] == "fresh"
    assert price_states["$99/mo"] == "stale"
