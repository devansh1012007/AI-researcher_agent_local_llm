# Development

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest            # 40 tests, fully offline (fake search/HTTP/LLM), ~3s
```

## Test layout

| Suite | Covers |
|---|---|
| `tests/unit` | schemas, state machine, quote verification, claim dedup, query dedup/info-gain, budgets, convergence |
| `tests/integration` | full offline research loop, resume, startup mode, budget hard stop |
| `tests/failure` | bad LLM output, dead sources, duplicate content race, corrupted cache |
| `tests/evaluation` | golden-task quality gates |

Offline testing is a design constraint: `tests/fakes.py` provides a scripted LLM,
fake search providers and an httpx MockTransport serving canned documents. The
orchestrator accepts injected fakes (`_make_document_processor`, registry, router cache).

## Adding a component

1. **Provider**: implement the interface in `providers/…`, register in
   `core/orchestrator.build_default_registry` (or config). Add unit tests with fakes.
2. **Prompt change**: add `v2.txt` (+ `.meta.yaml`) next to v1 — versions are never edited.
3. **New model field**: extend the Pydantic model + repository index columns; bump
   `SCHEMA_VERSION` if a new column is required and add an `_migrate` entry.

## Conventions

- Determinism first: hashing, dedup, chunking, budget math are pure functions.
- LLM calls always go through `ModelRouter` roles; never call providers ad hoc.
- Every persisted entity: stable ID prefix (`ev_`, `clm_`, `gap_`, ...), project_id,
  timestamps.
- Events: every phase records to `events.jsonl` AND a human line to
  `reports/research_log.md`.

## Manual verification flow

```bash
research new --mode academic "test question" --no-run   # create only
research run <id>                                        # execute
sqlite3 research_data/<id>/db.sqlite "select id,status from evidence limit 20"
```
