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

## Tools (spec #28)

| Tool | Permission | Notes |
|---|---|---|
| create_research_project | RESEARCH | returns project id + hint |
| start_research | RESEARCH | returns job identity immediately (#31) |
| get_research_status | READ | state/budget/counts/progress |
| pause/resume/cancel_research | RESEARCH | graceful lifecycle |
| get_job_status | READ | poll long jobs incl. task states |
| get_research_report | READ | markdown by name (traversal-guarded) |
| search_research_memory / ask_research_memory | READ | hybrid retrieval / grounded QA |
| get_claim · trace_claim · get_evidence | READ | provenance chains |
| get_gaps · get_contradictions · list_hypotheses | READ | ranked views |
| generate_hypotheses | RESEARCH | competing sets from gaps/contradictions |
| design_methodology | RESEARCH | 3-tier designs w/ pre-registered criteria |
| add_experiment_result | WRITE | verdict vs pre-registered criteria |

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
