# GAR — Grounded Agentic Researcher

A **local-first, evidence-first research engine** for deep literature and startup/market
research. GAR does not "summarize the web" — it runs a controlled research loop that
discovers sources, extracts verbatim-grounded evidence, verifies every quote against its
document, tracks claims/provenance in SQLite, detects contradictions and gaps, iterates
under explicit budgets, and produces fully traceable reports.

```
QUESTION → PROBLEM → RESEARCH PLAN → SEARCH → SOURCE → DOCUMENT → EVIDENCE
    → CLAIMS → GAPS / CONTRADICTIONS → TARGETED SEARCH → CONVERGENCE → SYNTHESIS
```

## What it does differently

| Typical "research agent" | GAR |
|---|---|
| LLM is the state machine | Deterministic orchestrator owns state; LLM only *proposes* |
| Markdown file as database | SQLite is the source of truth; Markdown reports are derived views |
| Trusts LLM output | Every quote verified against chunk text; unverifiable evidence rejected & audited |
| One giant prompt | Versioned externalized prompt templates; structured JSON validated by Pydantic |
| Recursion until "satisfied" | Hard budgets + convergence signals; stop reason always recorded |
| Pile of URLs at the end | Traceability chain: report claim → claim ID → evidence ID → document → source URL |

## Architecture

See [docs/architecture.md](docs/architecture.md). In short:

- `core/orchestrator.py` — central harness: state machine, budgets, checkpointing
- `models/` — Pydantic domain models (Evidence, Claim, Source, Gap, ...)
- `providers/` — LLM (Ollama / OpenAI-compatible / llama.cpp / mock), web search
  (DuckDuckGo / SearXNG), academic APIs (OpenAlex / Crossref / arXiv / Semantic Scholar)
- `pipeline/` — clarification, planning, retrieval, fetching, extraction, chunking,
  evidence extraction/validation/dedup
- `reasoning/` — gap detection, contradiction detection, convergence
- `reports/` — synthesis worker + deterministic markdown generation from DB state
- `storage/` — SQLite (WAL + FTS5), repositories, caches, JSONL event log
- `prompts/templates/` — versioned prompt templates with YAML system prompts
- `modes/` — academic and startup research modes sharing one core engine

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                       # full offline test suite (no network/model needed)
```

### Local inference

Point `gar.yaml` at your local runtime (see `gar.example.yaml`):

```yaml
models:
  extractor:  { provider: ollama, model: qwen2.5:7b }
  reasoning:  { provider: ollama, model: qwen2.5:14b }
  synthesis:  { provider: ollama, model: qwen2.5:14b }
```

Supported providers: `ollama`, `openai_compatible` (LM Studio/vLLM/llama.cpp server),
`llama_cpp`, `mock`. All roles may point at the same model. Without any model the engine
still runs end-to-end using deterministic fallbacks (extraction yields nothing, but
search/fetch/dedup/gaps/reports all function).

For reliable general web search, a local SearXNG instance is recommended:

```yaml
search: { web_provider: duckduckgo, searxng_base_url: "http://localhost:8080" }
```

## Running research

```bash
research new --mode academic "What are the most promising approaches for using \
    LLMs for robotic manipulation planning?"
research new --mode startup "Find promising startup opportunities around AI \
    infrastructure for small businesses in India."

research status   <project_id>     # live dashboard
research inspect  <project_id>     # problem / plan / claims
research evidence <project_id> --search "benchmark"
research gaps     <project_id>
research sources  <project_id>
research report   <project_id>     # regenerate markdown from DB
research pause/resume <project_id>
```

Reports land in `research_data/<project_id>/reports/`: `problem.md`,
`research_plan.md`, `info.md`, `sources.md`, `gaps.md`, `research_log.md`, plus
`literature_review.md` (academic) or `startup_research.md` (startup). Full audit data:
`events.jsonl`, `db.sqlite`, raw downloaded documents under `raw/`.

## Project structure

```
src/research_engine/
    core/        orchestrator, state machine, budgets, config
    models/      Pydantic entities (Evidence, Claim, Gap, Contradiction, ...)
    providers/   llm/ search/ academic/
    pipeline/    clarification planning retrieval fetching documents evidence routing
    reasoning/   gap_detector contradiction_detector convergence
    reports/     generator + synthesis worker
    prompts/     registry + versioned templates
    modes/       academic + startup
    cli/         `research` command
tests/           unit / integration / failure / evaluation (fully offline)
evals/           golden tasks + metrics + runner (`run_eval.py`)
skills/          domain playbooks (markdown)
docs/            architecture & subsystem docs
research_data/   per-project workspaces (gitignored)
```

## Limitations (Phase 1)

- Evidence **extraction quality depends on the local model**; small models need tight
  prompting (provided) and produce less than frontier-model yield.
- Keyless web search (DuckDuckGo HTML) is best-effort; SearXNG recommended.
- No vector/RAG Q&A yet (schema and FTS5 search are ready for it).
- Review gates pause but do not yet offer inline editing.
- Startup mode shares the generic engine; niche/opportunity generation is deferred.

## Roadmap

1. Local model quality pass (extraction prompts per model family)
2. Vector embeddings over chunks (optional, pluggable)
3. MCP server exposing existing tool interfaces
4. Hypothesis / methodology / finance modes on the same core
5. REST API + minimal UI on top of the orchestrator API
