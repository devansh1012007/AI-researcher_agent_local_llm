# REST API

Thin adapter over application services (spec #23/#71). The API never touches
SQLite and contains no business logic. OpenAPI docs auto-generated at
`/docs` (FastAPI, spec #128).

## Running

```bash
research serve                 # binds 127.0.0.1:8000 by default
research serve --port 8080
```

External binding requires a token — the CLI refuses otherwise (#67):

```bash
GAR_PLATFORM__API__AUTH_TOKEN=... research serve --host 0.0.0.0
# clients send: X-API-Token: ...
```

The token is required exactly when the server is bound to a non-loopback
address, and the address the server binds is the one the API authorises on
(INV-014) — `--host` wins over `platform.api.host`, and the CLI propagates it
to the app. Loopback binds (`127.0.0.1`, `::1`, `localhost`) are trusted and
need no token. Only `X-API-Token` is accepted; there is no `Authorization`
header support.

Unauthenticated on any bind: `GET /health`, `GET /ready`, `GET /info`, and
FastAPI's own `/docs`, `/redoc` and `/openapi.json`. Every other route —
including the `GET /events/stream` feed, which carries all event types — needs
the token on an external bind.

## Endpoints

### Health
- `GET /health` — overall + per-component: database, storage, llm, scheduler, events
  with levels healthy/degraded/unavailable (#51)
- `GET /ready`
- `GET /info`

### Projects
- `POST /projects` `{question, mode}` → 201 project
- `GET /projects`
- `GET /projects/{project_id}`
- `DELETE /projects/{project_id}`
- `GET /projects/{project_id}/status` — state, budget, counts, **meaningful progress**
  (branches answered, high-priority gaps open — never fake percentages, #110)
- `POST /projects/{project_id}/run`
- `POST /projects/{project_id}/pause`
- `POST /projects/{project_id}/resume`
- `POST /projects/{project_id}/cancel`
- `POST /projects/{project_id}/query` — grounded Q&A (answer or honest insufficiency)
- `POST /projects/{project_id}/search` — hybrid memory retrieval

### Knowledge & Review
- `GET /projects/{project_id}/evidence`
- `GET /projects/{project_id}/claims`
- `GET /projects/{project_id}/gaps`
- `GET /projects/{project_id}/contradictions`
- `GET /projects/{project_id}/hypotheses`
- `POST /projects/{project_id}/hypotheses/generate`
- `GET /projects/{project_id}/reports`
- `GET /projects/{project_id}/reports/{name}` — path traversal rejected
- `POST /projects/{project_id}/review/decisions` — record an analyst review decision (`claim`, `contradiction`, `validation_plan`) as an overlay without rewriting machine state

### Engines, Clarifying Questions & Source Trail
- `GET /engines` — list available research engine packs (`academic`, `startup`, `generic`, custom)
- `GET /engines/{name}` — inspect resolved manifest, loop, routes, and 6-layer effective config provenance
- `GET /projects/{project_id}/questions` — list clarifying questions for a project
- `POST /projects/{project_id}/questions/{question_id}/answer` — answer or skip a clarifying question (overrides assumption and records `USER_OBSERVATION` evidence)
- `GET /projects/{project_id}/trail` — unified forward/backward source trail and negative trail (`claim_id` or `source_id` optional filters)

### Jobs (asynchronous by design, #25/#26)
- `GET /jobs`
- `POST /jobs` → 202 `{job_id, status}`
- `GET /jobs/{job_id}` incl. task states
- `POST /jobs/{job_id}/pause`
- `POST /jobs/{job_id}/resume`
- `POST /jobs/{job_id}/cancel`
- `POST /tasks/{task_id}/retry` — manual retry of dead-lettered work

### Events
- `GET /events` — persisted audit stream (#75)
- `GET /events/stream` — SSE live stream (#108); keepalives every 15s

### Experiments
- `POST /projects/{project_id}/experiments` — register against hypothesis+methodology
- `POST /projects/{project_id}/experiments/{exp_id}/execute` — queues sandboxed run (202)
- `POST /projects/{project_id}/experiments/{exp_id}/result` — verdict vs pre-registered criteria

### Startup Specialist
- `POST /startup/research` — full startup pipeline: discovery -> hypotheses -> validation -> decision
- `POST /startup/discover` — evidence-pattern opportunity discovery
- `GET /startup/market-map` — market definition, gaps, segments, competitors, trends
- `GET /startup/segments` — customer segments, personas, pains, alternatives, workflow
- `GET /startup/competitors` — competitor profiles, pricing plans, distribution, gaps
- `GET /startup/opportunities/{opportunity_id}` — due diligence on one opportunity
- `POST /startup/validate` — design ranked validation tests + staged sequence
- `POST /startup/compare` — side-by-side opportunity comparison matrix + tradeoffs

## Error schema (#24)

```json
{"error": {"code": "NOT_FOUND", "message": "project not found: proj_x", "trace_id": "..."}}
```

Codes map to HTTP semantics: NOT_FOUND→404, CONFLICT→409,
UNAUTHORIZED→401/403, VALIDATION_ERROR→422, UPSTREAM_FAILURE/SERVICE_ERROR→502.
