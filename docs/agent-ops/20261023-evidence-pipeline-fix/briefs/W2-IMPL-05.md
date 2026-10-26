# Brief — W2-IMPL-05 (IMPL) · wave 2 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Add `policy` parameter to `build_provider()` in `providers/llm/router.py` and update `ModelRouter` to build and pass an `EgressPolicy` from `app_cfg`. This is C09 part A — the LLM provider factory must accept and forward an egress policy so LLM calls are governed by LOCAL_ONLY.
Why this matters: `build_provider()` is the single funnel for LLM provider construction. Without a `policy` parameter, LLM providers constructed through `ModelRouter` cannot enforce egress at request time. `ModelRouter` is constructed at `orchestrator.py:51` with `ModelRouter(cfg)`.

Your role: implementer.

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§11 testing philosophy, §12 data/concurrency/security)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md (commands, baseline, hotspots)
4. Plan: docs/plans/2026-10-22-evidence-pipeline-and-analyst-review.md — items C09, C23
5. Investigation findings: `router.py:27` `build_provider(cfg: LLMRoleConfig)` — no policy param; `ModelRouter.__init__` takes `app_cfg` (line 36); `ModelRouter.for_role` calls `build_provider(role_cfg)` (line 44); `core/http_policy.py` has `EgressPolicy` and `build_egress_policy(cfg)` (lines 13-48)
6. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/report-implementation.md
7. COMMS.md from the last WAVE-START

## 3. Task and acceptance criteria
Task T-005 (C09 part A):
1. Add `policy: EgressPolicy | None = None` parameter to `build_provider(cfg, policy=None)` in `router.py:27`
2. Update `ModelRouter.__init__` to build `self.policy = build_egress_policy(app_cfg)` (line 36-38)
3. Update `ModelRouter.for_role` to pass `self.policy` to `build_provider(role_cfg, self.policy)` (line 44)
4. `build_provider` does NOT need to call `policy.require()` itself — that's done by individual provider classes. It just needs to accept and store the policy.

Acceptance criteria (measurable):
- `build_provider(cfg, policy=None)` accepts optional `policy` parameter (default None for backward compatibility)
- `ModelRouter.__init__` builds `self.policy` from `build_egress_policy(app_cfg)`
- `ModelRouter.for_role(role)` passes `self.policy` to `build_provider(role_cfg, self.policy)`
- Existing callers of `build_provider(cfg)` without `policy` still work (default None)
- Scoped command: `.venv/bin/python -m pytest tests/unit/ -k "router or model_router or build_provider" -v` passes

Tests that must exist and fail without the fix:
- N/A (this is infrastructure for other agents; the actual egress enforcement is in provider files owned by W2-IMPL-06 through W2-IMPL-10)

Commands that must pass (scoped): `.venv/bin/python -m pytest tests/unit/ -k "router or model_router or build_provider" -v`

## 4. Ownership
WRITE-SET (may edit):
- `src/research_engine/providers/llm/router.py` (lines 27, 36-44)
READ-ONLY: everything else
FORBIDDEN: `src/research_engine/providers/llm/ollama.py`, `openai_compat.py` (owned by W2-IMPL-09), all other provider files

Need something outside? Post `NEED`; report `DEFERRED-DEPENDENCY`.

## 5. Parallel siblings this wave
| Agent | Task | Owns | Contracts it changes |
|---|---|---|---|
| W2-IMPL-06 | C09 part B (openalex, crossref) | providers/academic/openalex.py, crossref.py | Provider constructors gain `policy` param |
| W2-IMPL-07 | C09 part C (arxiv, semantic_scholar) | providers/academic/arxiv.py, semantic_scholar.py | Provider constructors gain `policy` param |
| W2-IMPL-08 | C09 part D (duckduckgo) | providers/search/duckduckgo.py | Provider constructor gains `policy` param |
| W2-IMPL-09 | C09 part E (ollama, openai_compat) | providers/llm/ollama.py, openai_compat.py | Provider constructors gain `policy` param; `build_provider` signature change affects them |
| W2-IMPL-10 | C09 part E (embeddings) | providers/embeddings/base.py, memory/retrieval.py | Provider constructors gain `policy` param |
| W2-IMPL-11 | C09 part F (fetching) | pipeline/fetching.py | `DocumentFetcher` builds and uses `EgressPolicy` |
| W2-IMPL-12 | C09 part G (orchestrator) | core/orchestrator.py | `build_default_registry` passes `policy` to provider constructors |

Known interactions: W2-IMPL-05 changes `build_provider` signature. W2-IMPL-09's providers (ollama, openai_compat) are constructed via `build_provider`, so they MUST accept the `policy` parameter that `build_provider` will pass. W2-IMPL-06 through W2-IMPL-10's providers are constructed in `build_default_registry` (W2-IMPL-12) or `memory/retrieval.py` (W2-IMPL-10), so they also need `policy` in their constructors. All constructors should use `policy: EgressPolicy | None = None` default so existing callers don't break. You cannot see their uncommitted work.

## 6. Skip list and known traps
Already fixed (don't redo): `core/http_policy.py` `EgressPolicy` class is complete and correct; `build_egress_policy(cfg)` works; `build_default_registry` already returns empty registry under LOCAL_ONLY
False leads: don't add `policy.require()` calls in `build_provider` itself — that's the provider classes' job (they know the host they're calling)
Flaky/pre-existing failures: none identified at baseline
Gotchas: `build_provider` is called from `ModelRouter.for_role` only (one call site). `ModelRouter` is constructed from `orchestrator.py:51` with `ModelRouter(cfg)`. The `cfg` has `.platform.effective_environment()` which `build_egress_policy` uses.

## 7. Environment and tests
Scoped commands: `.venv/bin/python -m pytest tests/unit/ -k "router or model_router or build_provider" -v`
Unique test resources: none needed
Do NOT: full suite, container restarts, shared-DB migrations, fixed ports

## 8. Deliverables
Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w2-impl/W2-IMPL-05-T-005.md
Commits: code first, then report (docs-only), trailers: Task / Agent / Wave / Report
Final message (≤ 8 lines): STATUS | agent | task | report path | commit SHAs | blockers

## 9. Role-specific notes
- Implementer: `build_provider` signature change must be backward-compatible (`policy=None` default). `ModelRouter` builds policy once in `__init__` and reuses it across `for_role` calls. Don't import `EgressPolicy` directly — use `build_egress_policy` from `core.http_policy` which reads `cfg.platform.effective_environment()`.
