# GAR — Grounded Agentic Researcher

**GAR (Grounded Agentic Researcher)** is a local-first, evidence-first research engine for deep academic and startup/market research. A deterministic orchestrator controls state transitions, budgets, retries, persistence, and convergence, while LLMs only *propose* plans, extractions, hypotheses, and syntheses. Every claim is grounded in verbatim-quoted source evidence, verified against source chunks, cross-checked for contradictions, and stored in an auditable SQLite + JSONL workspace.

## Core Principles

- **Evidence-first grounding (INV-005):** A claim is grounded only when a verbatim quote exists in the source chunk *and* deterministic support verification (`pipeline/claim_support.py`) confirms the quote supports the claim. Contradicting or unrelated extractions are stored as `REJECTED` for auditability and excluded from synthesis.
- **Deterministic orchestration:** State transitions (`core/state_machine.py`), resource budgets (`core/budget.py`), quality-and-independence weighting (`INV-007`), and convergence decisions (`reasoning/convergence.py`, `INV-006`) are owned by deterministic code, never LLM memory.
- **Failure ≠ empty results (INV-012):** Search, academic, fetch, and LLM boundaries distinguish transport/provider failures from genuine empty results. An all-provider outage with zero new evidence yields `StopReason.PROVIDER_DEGRADED`, never `CONVERGED`.
- **Collision-free monotonic ULIDs (INV-028):** Persisted entities use prefixed 26-character Crockford base32 monotonic ULIDs (`ev_01H...`, `clm_01H...`, `hyp_01H...`), preventing cross-process primary-key collisions while keeping legacy IDs readable.
- **Enforced privacy & egress boundary (INV-027):** Setting `platform.mode: offline` or `platform.security.privacy_mode: true` (`LOCAL_ONLY`) disables network provider construction and enforces loopback-only egress across all HTTP call sites and redirect hops.
- **Append-only analyst review overlay (INV-023):** Human review verdicts (`research review decide|list|revise`) are stored in an append-only overlay (`review_decisions`) keyed by content hash, filtering rejected claims at report-generation time without mutating machine-owned primary tables (`INV-004`).

## Quickstart & Setup

Requires Python ≥ 3.11 (3.12 supported).

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
source .venv/bin/activate
```

*(Or run `bash scripts/setup_dev.sh`, which uses `uv` when available.)*

`gar.yaml` is optional. By default, `AppConfig.load()` looks for `gar.yaml` / `gar.yml` / `config/gar.yaml` and falls back to safe laptop defaults (`mock` LLM, `research_data/` storage). Copy `gar.example.yaml` to `gar.yaml` to configure local Ollama or OpenAI-compatible endpoints. Environment overrides use `GAR_SECTION__KEY=value` (see `.env.example` and `docs/configuration.md`).

## Usage

```bash
# System health & environment check
research doctor

# Create and run an academic or startup research project
research new --mode academic "What are the main failure modes of LLM planners?"
research new --mode startup "Find promising AI bookkeeping opportunities for Indian SMBs"
research run <project_id>

# Grounded Q&A and claim provenance tracing (using prefixed ULIDs)
research ask <project_id> "What evidence supports the primary bottleneck?"
research trace-claim <project_id> clm_01HQ8XM3K7P9R4T2V6Y0Z1A3B

# Analyst review overlay
research review decide <project_id> --kind claim --target clm_01HQ8XM3K7P9R4T2V6Y0Z1A3B --verdict REJECTED --note "Outdated cohort"
research review list <project_id>

# Serve REST API (loopback 127.0.0.1:8000 open by default; external binds require X-API-Token)
research serve --host 127.0.0.1 --port 8000

# Run MCP stdio server
research mcp
```

## Testing, Verification & CI Gates

All unit, integration, and invariant suites run **100% offline** using deterministic fakes (`tests/fakes.py`). See `docs/CI.md` for full release-gate details.

```bash
python -m pytest                                     # Full offline test suite
python -m pytest tests/invariants                    # Executable system invariants (INV-001..INV-029)
python scripts/mutation_check.py                     # Critical mutation harness (all mutations must be DETECTED)
python scripts/reaudit.py                            # Replay original audit reproductions (14/14)
python scripts/check_dist.py                         # Built wheel & package-data self-sufficiency gate
python evals/runners/run_eval.py --offline           # Offline evaluation tasks & quality gates
python evals/runners/run_goldset.py                  # Content-keyed gold-set benchmark with Wilson/bootstrap CIs
```

## Architecture & Documentation

Everything under `src/research_engine/` follows strict service boundaries (`INV-008`: CLI, REST API, and MCP adapters route through `services/*` and `specialists/*/service.py`). Detailed subsystem contracts live in `docs/`:

- `docs/architecture.md` — System layout, orchestrator state machine, and component responsibilities
- `docs/invariants.md` — Canonical executable invariants (`INV-001` through `INV-029`)
- `docs/configuration.md` & `docs/security.md` — Environment modes (`offline` / `local` / `online`), `EgressPolicy`, API auth boundary (`INV-014`), and experiment sandboxing
- `docs/api.md` & `docs/mcp.md` — REST API endpoints, error envelope contract, and MCP stdio tools
- `docs/CI.md` — GitHub Actions workflow jobs and local gate reproduction
- `docs/development.md` & `docs/testing-strategy.md` — Developer workflows, hermetic fixtures, and adding components
