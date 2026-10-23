## What this repo is

**GAR (Grounded Agentic Researcher)** — a local-first, evidence-first research engine. A deterministic orchestrator owns the loop; the LLM only *proposes*. It discovers sources, extracts verbatim-quoted evidence, verifies quotes against source text, builds a claim/evidence graph, hunts contradictions, and emits traceable reports. Two modes: academic and startup/market research. ~137 Python modules, 55 CLI commands, REST API (45 routes), MCP server (29 tools), scheduler, backups, sandboxed experiments.

## Is it working?

**Yes, as software. Not yet verified as a research product.**

- Verified just now: `308 passed, 1 skipped in 109s`; offline eval gates PASS; `research doctor` reports degraded only because no scheduler/LLM is running.
- The **platform skeleton is genuinely solid**: fenced lease/scheduler, SQLite invariants, backup/restore, auth boundary, packaging.
- But three **P0 defects remain open**:
  - ID collisions across processes silently overwrite rows (`core/ids.py:13`) — data integrity.
  - `privacy_mode`/`local_only` are decorative; web providers are always registered (`core/orchestrator.py:649`).
  - Experiment sandbox write-root is rebindable from user code (`experiments/runner.py:28`).
- Two retrieval legs are structurally dead: `forum` resolves nowhere (`pipeline/retrieval.py:105`) and the watcher's academic leg calls a nonexistent attribute (`platform/watchers.py:163`) — so startup pain discovery and "living research" are weaker than advertised.
- **Live behavior is unverified.** Your `gar.yaml` points at Ollama (`qwen2.5:7b/14b`), which isn't reachable here, and there are no real-model quality benchmarks — only scripted offline fakes that run in ~2s.

## How refined is the experience?

**Broad, but demo-grade polish.** Command surface is huge (46 top-level + 9 `startup`), yet:

- `serve`, `mcp`, `jobs`, `doctor`, and all `startup *` commands **ignore `--config`** (`cli/main.py:636`), so they use defaults.
- Project listing omits `created_at`/`question_raw` while consumers read them → "reuse latest project" silently doesn't work; you get duplicate projects (`services/research_service.py:82`).
- Silent failures: ~12 bare `except: pass`; `generate-hypotheses` prints an error and still exits 0.
- Leftover debris (`{e and ''}` at `cli/main.py:282`), no `--json` output, no `--version`, stale docs (README says 80 tests; actual 308).
- No web UI. Interface is CLI / REST / MCP only.

## What to add (highest value first)

1. **Fix the evidence pipeline's dead legs + P0s.** Forum routing, watcher academic leg, ULID IDs, real privacy enforcement. Without these the core claim ("evidence-first") is partly hollow.
2. **Real-model quality benchmark** — a small gold set where human-labeled claims measure precision/recall of support, contradiction, and opportunity scoring. This is the single biggest unknown and the thing that makes or breaks the product.
3. **Analyst review workflow** — approve/reject claims, annotate contradictions, edit validation plans. The audit trail already exists; humans need to sign off.
4. **A read-only web UI** — project list, evidence graph, contradiction register, report viewer. The API already supports it.
5. **Cost/latency metering** — token + dollar accounting per project. Budgets exist but count calls, not money.
6. **Export formats** — DOCX/PDF evidence appendices; buyers don't consume Markdown.
7. **Project-selection/config correctness + JSON output** — cheap, removes most of the UX friction.

## Is it monetizable?

**Conditionally yes — but not as SaaS today.**

Strengths: real quote verification, claim-support gating, contradiction preservation, and the falsification workflow (assumptions → cheapest decisive test → decision rule) are genuinely differentiated. That's a sellable "auditable research" story.

Missing for SaaS: multi-tenancy, per-user auth, billing, quotas, UI, distributed workers, cost controls — all absent (`services/context.py:91` is a single global context).

Recommended path:

1. **Near term:** sell evidence-trailed research as a **fixed-scope service / pilot** in one vertical (e.g., startup opportunity memos for a specific market). Uses the code as-is plus human review.
2. **Then:** self-hosted/private-deployment license + support for privacy-sensitive buyers (fits the local-first design).
3. **Only then:** hosted SaaS, after real quality and unit economics are proven.

Caveat: MIT license means the code isn't a moat — trust, vertical workflows, and evaluation data are.

**Bottom line:** a well-engineered reliability skeleton wrapped around a heuristic research layer, currently late-prototype. Fix the three P0s and the two dead retrieval legs, then run 10–20 real-model tasks and measure quality — that determines whether the monetization story is real.