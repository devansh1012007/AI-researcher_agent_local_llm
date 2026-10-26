# MCP Server

The platform exposes itself to MCP clients as **capabilities, not
orchestration** (spec #27/#161): every tool maps onto an application service;
MCP never re-implements research logic and never gets shells.

## Running

```bash
research mcp          # JSON-RPC 2.0 over stdio; add to your MCP client config:
# {"command": "<abs-path>/.venv/bin/research", "args": ["mcp"]}
```

Implemented methods: `initialize`, `tools/list`, `tools/call`,
`resources/list`, `resources/templates/list`, `resources/read`, `ping`.
Stdio requests are bounded to a maximum line length of 1 MiB (1,048,576 bytes);
oversized lines return JSON-RPC error `-32600` (`Invalid Request: line exceeds 1 MiB limit`) without terminating the server.

## Tools (spec #28)

| Tool | Permission | Notes |
|---|---|---|
| `create_research_project` | RESEARCH | returns project id + hint |
| `start_research` | RESEARCH | returns job identity immediately (#31) |
| `get_research_status` | READ | state/budget/counts/progress |
| `pause_research` | RESEARCH | pause running research for a project |
| `resume_research` | RESEARCH | resume paused research |
| `cancel_research` | RESEARCH | cancel running research (graceful) |
| `get_job_status` | READ | poll long jobs incl. task states |
| `get_research_report` | READ | markdown by name (traversal-guarded) |
| `search_research_memory` | READ | hybrid retrieval over stored evidence chunks |
| `ask_research_memory` | READ | grounded Q&A with citation-backed answer |
| `get_claim` | READ | claim detail with evidence provenance chain |
| `trace_claim` | READ | full claim -> evidence -> source provenance chain (annotated with `role`) |
| `get_evidence` | READ | evidence item with its source |
| `get_gaps` | READ | open research gaps sorted by importance |
| `get_contradictions` | READ | detected contradictions between claims |
| `list_hypotheses` | READ | ranked hypothesis portfolio |
| `generate_hypotheses` | RESEARCH | competing sets from gaps/contradictions |
| `design_methodology` | RESEARCH | 3-tier designs w/ pre-registered criteria |
| `add_experiment_result` | WRITE | verdict vs pre-registered criteria |
| `record_review_decision` | WRITE | analyst review decision overlay on claim/contradiction/validation_plan |
| `list_engines` | READ | list available declarative research engine packs and categories |
| `get_pending_questions` | READ | list clarifying questions for a project |
| `answer_question` | WRITE | answer or skip a clarifying question for a project |
| `get_source_trail` | READ | unified source trail and negative trail for a project, claim, or source |
| `startup_research` | RESEARCH | full startup pipeline: discovery -> hypotheses -> validation -> decision |
| `startup_discover_opportunities` | RESEARCH | evidence-pattern opportunity discovery |
| `startup_get_market_map` | READ | market map: definition, gaps, segments, competitors, trends |
| `startup_get_customer_segments` | READ | customer research: segments, personas, pains, alternatives, workflow |
| `startup_get_competitors` | READ | competitor profiles, pricing plans, distribution, gaps |
| `startup_get_opportunities` | READ | scored, gated opportunity portfolio |
| `startup_analyze_opportunity` | READ | due diligence on one opportunity: rubric, readiness, recommendation |
| `startup_get_assumptions` | READ | ranked assumption register |
| `startup_design_validation` | RESEARCH | design ranked validation tests + staged sequence |
| `startup_compare_opportunities` | READ | side-by-side comparison matrix + tradeoffs |

## Resources (#29)

```
research://project/{id}                 summary: state, counts, progress, uncertainties
research://project/{id}/report/{name}   text/markdown
research://project/{id}/hypotheses      application/json
research://project/{id}/gaps            application/json
```

## Security model

- **Permissions (#33)**: tools declare `required_permission`
  (READ/RESEARCH/WRITE/EXECUTE_EXPERIMENT/ADMIN). Clients are configured with
  a grant set; default is **READ-only**. Higher grants imply lower ones —
  never the reverse. Denied calls return JSON-RPC error `-32001`.
- **No filesystem/shell exposure (#30/#165)**: no tool accepts arbitrary paths
  or commands; resources are constrained to `research://project/...` URIs.
- **Context discipline (#32)**: responses carry summaries, ids, and limits —
  never the full database. Clients request depth explicitly.
- Human gates hold regardless of client: experiments awaiting approval are
  reported as BLOCKED, not executed (#45).

## Limitations

Single-user local trust model; no per-tool audit UI yet (events are persisted
in `platform_events`); SSE-style progress arrives via job polling today.
