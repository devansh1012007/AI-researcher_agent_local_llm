# Brief — W2-IMPL-12 (IMPL) · wave 2 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Pass `EgressPolicy` from `build_default_registry()` into each provider constructor in `core/orchestrator.py`. This is C09 part G — the registry construction site must forward the policy to all providers it creates so they can enforce egress at request time.
Why this matters: `build_default_registry` already builds an `EgressPolicy` and returns an empty registry under LOCAL_ONLY (construction-time gating). But under HYBRID/ONLINE, it constructs providers without passing the policy, so request-time enforcement is missing. W2-IMPL-06 through W2-IMPL-10 add `policy` parameters to provider constructors; W2-IMPL-12 must actually pass the policy at this call site.

Your role: implementer.

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§11 testing philosophy, §12 data/concurrency/security)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md (commands, baseline, hotspots)
4. Plan: docs/plans/2026-10-22-evidence-pipeline-and-analyst-review.md — items C09, C23
5. Investigation findings: `orchestrator.py:650-679` `build_default_registry(cfg)` — line 652 `policy = build_egress_policy(cfg)`, lines 657-658 return empty registry under `policy.strict`, lines 671-678 construct `OpenAlexProvider(timeout=timeout)`, `CrossrefProvider(timeout=timeout)`, `ArxivProvider(timeout=timeout)`, `SemanticScholarProvider(api_key, timeout)`, `DuckDuckGoProvider(timeout=timeout)`, `SearxngProvider(base_url, timeout)` — NONE pass `policy`
6. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/report-implementation.md
7. COMMS.md from the last WAVE-START

## 3. Task and acceptance criteria
Task T-012 (C09 part G):
1. In `build_default_registry`: after `policy = build_egress_policy(cfg)` (line 652), pass `policy=policy` to every provider constructor:
   - `DuckDuckGoProvider(timeout=timeout, policy=policy)` (line 666)
   - `SearxngProvider(cfg.search.searxng_base_url, timeout, policy=policy)` (line 668)
   - `OpenAlexProvider(timeout=timeout, policy=policy)` (line 671)
   - `CrossrefProvider(timeout=timeout, policy=policy)` (line 672)
   - `ArxivProvider(timeout=timeout, policy=policy)` (line 673)
   - `SemanticScholarProvider(cfg.search.semantic_scholar_api_key, timeout, policy=policy)` (line 674)

Acceptance criteria (measurable):
- Every provider constructor call in `build_default_registry` passes `policy=policy`
- Under LOCAL_ONLY, `build_default_registry` still returns empty registry (line 657-658 unchanged)
- Under HYBRID/ONLINE, providers are constructed with `policy` and enforce egress at request time
- All provider constructors accept `policy` keyword argument (done by W2-IMPL-06 through W2-IMPL-10)
- Scoped command: `.venv/bin/python -m pytest tests/unit/ -k "registry or build_default or provider" -v` passes

Tests that must exist and fail without the fix:
- N/A (this is wiring; provider-level tests by W2-IMPL-06 through W2-IMPL-10 verify enforcement)

Commands that must pass (scoped): `.venv/bin/python -m pytest tests/unit/ -k "registry or build_default or provider" -v`

## 4. Ownership
WRITE-SET (may edit):
- `src/research_engine/core/orchestrator.py` (lines 666, 668, 671-674 — add `policy=policy` to 6 constructor calls)
READ-ONLY: everything else
FORBIDDEN: all provider files (owned by W2-IMPL-06 through W2-IMPL-10)

Need something outside? Post `NEED`; report `DEFERRED-DEPENDENCY`.

## 5. Parallel siblings this wave
| Agent | Task | Owns | Contracts it changes |
|---|---|---|---|
| W2-IMPL-05 | C09 part A (router.build_provider) | providers/llm/router.py | Not directly — LLM providers not in build_default_registry |
| W2-IMPL-06 | C09 part B (openalex, crossref) | providers/academic/ | Their constructors MUST accept `policy=policy` |
| W2-IMPL-07 | C09 part C (arxiv, semantic_scholar) | providers/academic/ | Their constructors MUST accept `policy=policy` |
| W2-IMPL-08 | C09 part D (duckduckgo) | providers/search/ | Their constructors MUST accept `policy=policy` |
| W2-IMPL-10 | C09 part E (embeddings) | providers/embeddings/ | Not directly — embeddings constructed in memory/retrieval.py (W2-IMPL-10) |

Known interactions: W2-IMPL-12 DEPENDS on W2-IMPL-06 through W2-IMPL-10 modifying their constructors to accept `policy`. All use `policy: EgressPolicy | None = None` default, so if W2-IMPL-12 commits before a constructor is updated, the intermediate state breaks — but the final state (after all Wave 2 agents complete) is correct. The gate runs after all Wave 2 agents complete. You cannot see their uncommitted work.

## 6. Skip list and known traps
Already fixed: `build_egress_policy(cfg)` called at line 652; `policy.strict` early return at lines 657-658
False leads: don't remove the early return under LOCAL_ONLY; don't change `policy.strict` logic
Flaky/pre-existing failures: none
Gotchas: 6 constructor calls to update. `policy` variable is already in scope at line 652. Use `policy=policy` keyword argument.

## 7. Environment and tests
Scoped commands: `.venv/bin/python -m pytest tests/unit/ -k "registry or build_default or provider" -v`
Unique test resources: none needed
Do NOT: full suite, container restarts, shared-DB migrations, fixed ports, live network calls

## 8. Deliverables
Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w2-impl/W2-IMPL-12-T-012.md
Commits: code first, then report (docs-only), trailers: Task / Agent / Wave / Report
Final message (≤ 8 lines): STATUS | agent | task | report path | commit SHAs | blockers

## 9. Role-specific notes
- Implementer: `policy` is already a local variable at line 652. Just add `policy=policy` to each of the 6 constructor calls. Do NOT modify the early return at lines 657-658.
