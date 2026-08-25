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

## Endpoints

### Health
- `GET /health` — overall + per-component: database, storage, llm, scheduler
  with levels healthy/degraded/unavailable (#51)
- `GET /ready`, `GET /info`

### Projects
- `POST /projects` `{question, mode}` → 201 project
- `GET /projects` · `GET /projects/{id}` · `DELETE /projects/{id}`
- `GET /projects/{id}/status` — state, budget, counts, **meaningful progress**
  (branches answered, high-priority gaps open — never fake percentages, #110)
- `POST /projects/{id}/run|pause|resume|cancel`
- `POST /projects/{id}/query` — grounded Q&A (answer or honest insufficiency)
- `POST /projects/{id}/search` — hybrid memory retrieval

### Knowledge
- `GET /projects/{id}/evidence|claims|gaps|contradictions|hypotheses|reports`
- `GET /projects/{id}/reports/{name}` — path traversal rejected
- pagination via `offset`/`limit` (bounded), filters where useful (#24)

### Jobs (asynchronous by design, #25/#26)
- `GET /jobs?status=&project_id=`
- `POST /jobs?type_=deep_research&project_id=` → 202 `{job_id, status}`
- `GET /jobs/{id}` incl. task states · `POST /jobs/{id}/pause|resume|cancel`
- `POST /tasks/{task_id}/retry` — manual retry of dead-lettered work

### Events
- `GET /events?project_id=&after_seq=` — persisted audit stream (#75)
- `GET /events/stream` — SSE live stream (#108); keepalives every 15s

### Experiments
- `POST /projects/{id}/experiments` — register against hypothesis+methodology
- `POST /projects/{id}/experiments/{exp}/execute` — queues sandboxed run (202)
- `POST /projects/{id}/experiments/{exp}/result` — verdict vs pre-registered criteria

## Error schema (#24)

```json
{"error": {"code": "NOT_FOUND", "message": "project not found: proj_x"}}
```

Codes map to HTTP semantics: NOT_FOUND→404, CONFLICT→409,
UNAUTHORIZED→401/403, UPSTREAM_FAILURE/SERVICE_ERROR→502.
