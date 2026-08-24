# GAR — Grounded Agentic Researcher

A **local-first, evidence-first research engine** for deep literature and startup/market
research. GAR does not "summarize the web" — it runs a controlled, **adaptive** research
loop that discovers sources, extracts verbatim-grounded evidence, verifies every quote
against its document, builds a research graph (claims, papers, concepts, competitors,
pains), detects contradictions and structural gaps, prioritizes what to research next,
and produces fully traceable reports.

```
QUESTION → PROBLEM → RESEARCH PLAN → SEARCH → SOURCE → DOCUMENT → EVIDENCE
    → CLAIMS → EVIDENCE GRAPH → GAPS / CONTRADICTIONS / WEAK CLAIMS
    → ADAPTIVE PLANNER (what next?) → TARGETED SEARCH → CONVERGENCE
    → LITERATURE / MARKET INTELLIGENCE → SYNTHESIS
```

## Phase 2 capabilities

| Area | What the system now does |
|---|---|
| Adaptive planning | priority-scored branches/gaps; strategy selection per iteration; explicit stop explanations |
| Research graph | typed entities + relationships in SQLite; evidence density; concept/paper/company nodes |
| Evidence quality | independence detection; aggregate strength (two blogs never beat one primary study); uncertainty labels |
| Literature intelligence | paper clustering (TF-IDF centroid linkage); foundational vs recent detection; benchmark tracking; guarded method comparison |
| Startup intelligence | pain-point registry; price observations; market signals; opportunity discovery from clustered evidence with transparent scoring |
| Falsification | critical assumptions per opportunity + cheapest-test/pass/fail/decision design |
| Memory | hybrid retrieval (FTS5 + optional embeddings); grounded Q&A that refuses when evidence is insufficient; claim tracing |
| Snapshots | consistent snapshots; iteration diffs with research gain; source update detection |

## What it does differently

| Typical "research agent" | GAR |
|---|---|
| LLM is the state machine | Deterministic orchestrator owns state; LLM only *proposes* |
| Markdown file as database | SQLite (+graph tables) is the source of truth; reports are derived views |
| Trusts LLM output | Every quote verified against chunk text; unverifiable evidence rejected & audited |
| Recursion until "satisfied" | Hard budgets + convergence signals + research-gain measurement; stop reason always explained |
| Confirmation machine | Adversarial engine hunts counter-evidence for high-confidence claims |
| Pile of URLs at the end | Traceability chain: report claim → claim ID → evidence ID → document → source URL |

## Architecture

See [docs/architecture.md](docs/architecture.md) and the subsystem docs:
[adaptive_research.md](docs/adaptive_research.md),
[research_graph.md](docs/research_graph.md),
[literature_intelligence.md](docs/literature_intelligence.md),
[startup_intelligence.md](docs/startup_intelligence.md),
[persistent_memory.md](docs/persistent_memory.md),
[contradiction_engine.md](docs/contradiction_engine.md),
[research_evaluation.md](docs/research_evaluation.md).

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                       # 80 tests, fully offline (no network/model needed)
```

### Local inference

Point `gar.yaml` at your local runtime (see `gar.example.yaml`):

```yaml
models:
  extractor:  { provider: ollama, model: qwen2.5:7b }
  reasoning:  { provider: ollama, model: qwen2.5:14b }
  synthesis:  { provider: ollama, model: qwen2.5:14b }

embeddings:
  provider: ollama           # or "hashing" for zero-dependency semantic-ish retrieval
  model: nomic-embed-text
```

Supported LLM providers: `ollama`, `openai_compatible` (LM Studio/vLLM/llama.cpp server),
`llama_cpp`, `mock`. All roles may point at the same model. Without any model the engine
still runs end-to-end using deterministic fallbacks.

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

research status   <id>          # live dashboard
research branches <id>          # branch coverage scores
research map      <id>          # literature map (academic) / market map (startup)
research papers   <id>          # paper entities
research ask      <id> "..."    # grounded Q&A over the archive (cited)
research trace-claim <id> clm_000001
research verify   <id> clm_000001   # queue adversarial verification searches
research opportunities <id>     # discovered+scored opportunities (startup)
research gaps / sources / evidence <id>
research diff     <id>          # what changed between iterations
research snapshot <id> --label pre
research replay   <id>          # step through the research process
research pause/resume/report <id>
```

Reports land in `research_data/<project_id>/reports/`. Academic projects additionally
get `literature_map.md`, `methods_comparison.md`, `benchmark_analysis.md`; startup
projects get `market_map.md`, `opportunity_map.md`, `validation_candidates.md`; all
projects get `evidence_map.md`, `contradiction_report.md`, `research_timeline.md`.

## Project structure

```
src/research_engine/
    core/        orchestrator, state machine, budgets, config
    models/      Pydantic entities (incl. startup models, opportunities)
    providers/   llm/ search/ academic/ embeddings/
    pipeline/    clarification planning retrieval fetching documents graph_builder ...
    reasoning/   adaptive_planner priority gap_detector structural_gaps adversarial
                 evidence_quality contradiction_analyzer convergence
    intelligence/ literature.py startup.py falsification.py
    memory/      retrieval.py qa.py snapshots.py
    reports/     generator.py synthesis.py intelligence_reports.py
    prompts/     registry + versioned templates
    modes/       academic + startup
    cli/         `research` command
tests/           unit / integration / failure / evaluation (fully offline, 80 tests)
evals/           golden tasks + phase2 tasks + metrics + runner
skills/          domain playbooks (markdown)
docs/            architecture & subsystem docs
research_data/   per-project workspaces (gitignored)
```

## Limitations

- Extraction quality depends on the local model; small models yield less.
- Keyless web search (DuckDuckGo HTML) is best-effort; SearXNG recommended.
- Hashing embeddings are lexical-only; configure Ollama embed models for real semantics.
- Paper similarity uses TF-IDF clustering, not deep embeddings (swap point exists).
- Hypothesis/methodology generation deferred by design — the data model is ready.

## Roadmap (Phase 3)

1. Hypothesis generation from the claim/evidence/contradiction graph
2. Methodology designer on top of benchmark comparisons
3. Watched sources/queries → incremental re-research alerts
4. MCP server exposing existing tool interfaces
5. REST API over the orchestrator/memory layers
