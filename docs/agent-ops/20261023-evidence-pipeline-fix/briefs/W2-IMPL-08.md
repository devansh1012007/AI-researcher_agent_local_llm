# Brief — W2-IMPL-08 (IMPL) · wave 2 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Route `httpx.get`/`httpx.post` calls in `providers/search/duckduckgo.py` through `EgressPolicy`. This is C09 part D — the DuckDuckGo search provider must refuse non-loopback hosts under LOCAL_ONLY at every outbound request. There are 3 direct `httpx` call sites (lines 55, 58, 104) plus `SearxngProvider` at line 104.
Why this matters: DuckDuckGo is the default web search provider. Its search calls must be governed by egress policy at request time.

Your role: implementer.

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§11 testing philosophy, §12 data/concurrency/security)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md (commands, baseline, hotspots)
4. Plan: docs/plans/2026-10-22-evidence-pipeline-and-analyst-review.md — items C09, C23
5. Investigation findings: `duckduckgo.py:55` `httpx.get(base, ...)`; `:58` `httpx.post(base, ...)`; `:104` `httpx.get(f"{self.base_url}/search", ...)` (SearxngProvider); all in `search()` methods; `DuckDuckGoProvider` constructed in `build_default_registry` (`orchestrator.py:666`) with `DuckDuckGoProvider(timeout=timeout)`; `SearxngProvider` constructed at `:668` with `SearxngProvider(cfg.search.searxng_base_url, timeout)`
6. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/report-implementation.md
7. COMMS.md from the last WAVE-START

## 3. Task and acceptance criteria
Task T-008 (C09 part D):
1. In `duckduckgo.py`: import `build_egress_policy` from `core.http_policy`; add `policy: EgressPolicy | None = None` to `DuckDuckGoProvider.__init__` and `SearxngProvider.__init__`; store `self.policy = policy`; before each `httpx.get`/`httpx.post` (lines 55, 58, 104), extract host from URL and call `self.policy.require(host, "duckduckgo search")` / `self.policy.require(host, "searxng search")` if `self.policy` is not None

Acceptance criteria (measurable):
- `DuckDuckGoProvider.__init__` accepts `policy: EgressPolicy | None = None`
- `SearxngProvider.__init__` accepts `policy: EgressPolicy | None = None`
- Before each `httpx.get`/`httpx.post`, host extracted via `urlparse(url).hostname`, `self.policy.require(host, "...")` called when `self.policy` is not None
- Under LOCAL_ONLY, `self.policy.require("html.duckduckgo.com", ...)` raises `RuntimeError`
- Existing constructors `DuckDuckGoProvider(timeout=timeout)`, `SearxngProvider(base_url, timeout)` still work
- Scoped command: `.venv/bin/python -m pytest tests/unit/ -k "duckduckgo or searxng or search" -v` passes

Tests that must exist and fail without the fix:
- Test constructing `DuckDuckGoProvider(policy=EgressPolicy("LOCAL_ONLY"))` and calling `search()` — should raise `RuntimeError` before network call

Commands that must pass (scoped): `.venv/bin/python -m pytest tests/unit/ -k "duckduckgo or searxng or search" -v`

## 4. Ownership
WRITE-SET (may edit):
- `src/research_engine/providers/search/duckduckgo.py`
READ-ONLY: everything else
FORBIDDEN: all other provider files

Need something outside? Post `NEED`; report `DEFERRED-DEPENDENCY`.

## 5. Parallel siblings this wave
| Agent | Task | Owns | Contracts it changes |
|---|---|---|---|
| W2-IMPL-05 | C09 part A (router.build_provider) | providers/llm/router.py | `build_provider` gains `policy` param |
| W2-IMPL-06 | C09 part B (openalex, crossref) | providers/academic/ | Same pattern |
| W2-IMPL-07 | C09 part C (arxiv, semantic_scholar) | providers/academic/ | Same pattern |
| W2-IMPL-09 | C09 part E (ollama, openai_compat) | providers/llm/ | Same pattern |
| W2-IMPL-10 | C09 part E (embeddings) | providers/embeddings/ | Same pattern |
| W2-IMPL-11 | C09 part F (fetching) | pipeline/fetching.py | `DocumentFetcher` uses `EgressPolicy` |
| W2-IMPL-12 | C09 part G (orchestrator) | core/orchestrator.py | Passes `policy` to `DuckDuckGoProvider` and `SearxngProvider` constructors |

Known interactions: W2-IMPL-12 passes `policy=policy` to `DuckDuckGoProvider(timeout=timeout, policy=policy)` and `SearxngProvider(base_url, timeout, policy=policy)`. Your constructors MUST accept `policy` keyword argument. Use `policy: EgressPolicy | None = None` default. You cannot see their uncommitted work.

## 6. Skip list and known traps
Already fixed: `core/http_policy.py` complete; construction-time gating works
False leads: don't modify `build_default_registry` (W2-IMPL-12's job)
Flaky/pre-existing failures: none
Gotchas: DuckDuckGo has 3 call sites (2 in `search()` GET/POST attempts, 1 in `SearxngProvider.search()`). All need `require()`. Host from `urlparse(url).hostname`.

## 7. Environment and tests
Scoped commands: `.venv/bin/python -m pytest tests/unit/ -k "duckduckgo or searxng or search" -v`
Unique test resources: none needed
Do NOT: full suite, container restarts, shared-DB migrations, fixed ports, live network calls

## 8. Deliverables
Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w2-impl/W2-IMPL-08-T-008.md
Commits: code first, then report (docs-only), trailers: Task / Agent / Wave / Report
Final message (≤ 8 lines): STATUS | agent | task | report path | commit SHAs | blockers

## 9. Role-specific notes
- Implementer: When `self.policy is None`, skip `require()` — backward compatibility. All 3 `httpx` call sites need the check.
