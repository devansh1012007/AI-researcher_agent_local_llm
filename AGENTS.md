# AGENTS.md

Local-first research engine (Python 3.11+). Deterministic orchestrator harness + LLM workers. Evidence provenance is sacred.

## Commands

```bash
source .venv/bin/activate            # venv already exists; pip install -e ".[dev]" to restore
pytest                               # full suite: 80 tests, ~6s, fully OFFLINE
pytest tests/unit/test_evidence_validation.py -k verify_quote   # single test pattern
python evals/runners/run_eval.py --offline                      # eval gates (loads all evals/datasets/*.json)

research new --mode academic "question"     # create + run project (LIVE network)
research new --mode startup "question" --no-run
research status|branches|map|ask|replay|diff <project_id>
```

- Tests never hit network or require Ollama — they use `tests/fakes.py` (ScriptedLLM, FakeSearchProvider, httpx MockTransport). Keep it that way.
- Live `research` runs need network. No local LLM configured → engine still completes using deterministic fallbacks, but evidence extraction yields nothing (by design).
- Eval runner inserts `sys.path` hacks for ROOT/tests; don't move those files.

## Architecture invariants (do not break)

- **Only the orchestrator** calls `StateMachine.transition()` / mutates project state / spends budgets. Workers propose; harness decides.
- **SQLite is the source of truth** (`research_data/<project_id>/db.sqlite`, WAL). Markdown reports are derived views regenerated from DB — never hand-edit them as state.
- Every evidence item must survive `verify_quote()` against its chunk text. Failures are stored as `status=REJECTED` on purpose (audit trail) — do not delete rejected rows.
- Claim confidence is *computed* from tier × confidence × corroboration (`reasoning/evidence_quality.py`); LLMs never assert it. Inference/assumption claims are never upgraded to FACT silently.

## Gotchas (each caused real bugs once)

- **Global caches**: fetch/search caches live at `<storage.data_dir>/_global/*.sqlite`. They persist across projects AND test/live runs — if a live run returns suspiciously fake-looking data, delete `research_data/_global/`. Never reintroduce CWD-relative cache paths.
- **SQLite threading**: first connection per thread runs PRAGMAs under `_init_lock` (Database + KVCache). Concurrent `PRAGMA journal_mode=WAL` races cause "database is locked". Content-hash dedup in `DocumentProcessor` also holds `_dedup_lock` across check+save.
- **Pydantic models**: class attrs like `PREFIX` need `ClassVar[str]`. Repos index columns tolerate both enums and strings via `_enum_val()` — when adding indexed columns, use it.
- **Branch.category is a plain string** (not BranchCategory enum) — never call `.value` on it.
- **Prompts are versioned files** at `src/research_engine/prompts/templates/<name>/vN.txt` + matching `vN.meta.yaml` (holds `system:`). To change a prompt, add `v2.*`; never edit v1. `render()` raises only on unfilled lowercase placeholders — web pages containing literal `{{...}}` must not crash rendering.
- **Regexes over scraped text**: trailing `\b` after `\d` fails on "$5M" (digit→letter is not a boundary). Startup price regex excludes funding magnitudes deliberately.
- `tests/conftest.py::make_orchestrator` wires offline fakes by subclassing Orchestrator and overriding `_make_document_processor()`. New IO paths should get a similar injection seam rather than monkey-patching.

## Config

Single YAML (`gar.yaml`, see `gar.example.yaml`) overridden by `GAR_SECTION__KEY=value` env vars (e.g. `GAR_MODELS__EXTRACTOR__PROVIDER=mock`). Defaults assume laptop hardware: `max_parallel_llm_tasks: 1` always, fetches bounded separately.

LLM providers: `ollama | openai_compatible | llama_cpp | mock`. Unknown provider falls back to mock with a warning (engine degrades gracefully — keep that behavior).

## Conventions

- Every persisted entity: stable prefixed ID (`ev_`, `clm_`, `gap_`, `src_`, ...) + `project_id` + timestamps. New tables go through `Database.upsert/get/list/count`; add indexed cols to both schema DDL and `_index_cols`.
- Schema changes: add column to `_SCHEMA`, bump nothing unless breaking — additive migrations go in `Database._migrate()`.
- Major events log twice: JSONL (`events.jsonl`) + human line (`reports/research_log.md`). Use `EventLog.record(..., human_line=...)`.
- Phase docs live in `docs/*.md`; subsystem behavior contracts (formulas, verdicts, scoring weights) are documented there — update the doc when changing the code.

## Phase 3 specifics

- Hypotheses live in `ReasoningRepos` (separate from `Repositories`); both bind to the same per-project DB. New reasoning tables go in `_EXTRA_TABLES` (database.py), not `_SCHEMA`.
- Hypothesis lifecycle transitions are validated (`ALLOWED_HYPO_TRANSITIONS`); result ingestion walks legal paths via BFS (`_walk_path`) — never set `.status` directly.
- Generation always produces COMPETING families (+null/artifact) linked via `alternative_of`; a lone hypothesis without rivals is a spec violation.
- Eval runner offline mode uses a FRESH temp workspace per task — project IDs derive from the question, so rerunning in a shared workspace collides per-process ID counters with stale rows (caused a real flake).
- `tests/fakes.py` FakeAcademicProvider generates query-hashed arXiv URLs so tier ratios stay realistic; keep that property when touching fixtures.

## Phase 4 specifics

- Platform state lives in `<data_dir>/platform.sqlite` (PlatformDB) — jobs/tasks/watchers/events/incidents. Project knowledge stays in per-project DBs. Never move scheduler state into Python globals (#118).
- `save_job` treats terminal statuses (COMPLETED/FAILED/FAILED_PARTIAL/CANCELLED) as ABSORBING: stale in-memory job objects cannot resurrect a finished/cancelled job. If adding new terminal states, update the SQL guard.
- Job finalization is event-driven (`_advance_one` after every task completion) — never rely on idle-poll timing for lifecycle correctness.
- Task claiming is a single atomic conditional UPDATE with lease columns; `lease_expires_at` is a real indexed column, not just JSON — keep both in sync when touching add_task/update_task.
- Experiment sandbox = audit-hook guard (network/subprocess/write containment) + RLIMIT_AS/CPU/NPROC + wall timeout + scrubbed env. The guard must run BEFORE user code via `-c` prefix; patching `socket.socket` breaks ssl imports.
- API binds 127.0.0.1 by default; `cmd_serve` hard-refuses non-local binding without an auth token — tests must pass host explicitly or they will start uvicorn and hang.
- MCP server is hand-rolled JSON-RPC over stdio; permission checks happen in `_call_tool` via PermissionEngine. Implication is downward-only (RESEARCH grants READ; READ does NOT grant RESEARCH) — the backwards check was a real security bug once.
- Eval runner offline mode uses fresh temp workspaces per task AND `expect_completed` gate asserts lifecycle state; quality gates live in `evals/runners/run_eval.py`.
