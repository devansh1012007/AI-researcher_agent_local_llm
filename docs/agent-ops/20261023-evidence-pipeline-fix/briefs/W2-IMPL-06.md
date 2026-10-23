# Brief — W2-IMPL-06 (IMPL) · wave 2 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Route `httpx.get` calls in `providers/academic/openalex.py` and `providers/academic/crossref.py` through `EgressPolicy`. This is C09 part B — academic search providers must refuse non-loopback hosts under LOCAL_ONLY at every outbound request, not just at construction time.
Why this matters: `build_default_registry` returns an empty registry under LOCAL_ONLY (construction-time gating works), but if an academic provider is constructed outside the registry, its `httpx.get` calls would still reach the network. Each provider must call `self.policy.require(host)` before each `httpx.get`.

Your role: implementer.

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§11 testing philosophy, §12 data/concurrency/security)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md (commands, baseline, hotspots)
4. Plan: docs/plans/2026-10-22-evidence-pipeline-and-analyst-review.md — items C09, C23
5. Investigation findings: `openalex.py:25` `httpx.get(f"{self.BASE}/works", ...)`; `crossref.py:24` `httpx.get(f"{self.BASE}/works", ...)`; both raise `SearchProviderError` on failure; `core/http_policy.py` `EgressPolicy.require(host, what)` raises `RuntimeError` if not allowed; providers are constructed in `build_default_registry` (`orchestrator.py:671-674`) with `OpenAlexProvider(timeout=timeout)`, `CrossrefProvider(timeout=timeout)`
6. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/report-implementation.md
7. COMMS.md from the last WAVE-START

## 3. Task and acceptance criteria
Task T-006 (C09 part B):
1. In `openalex.py`: import `EgressPolicy`/`build_egress_policy` from `core.http_policy`; add `policy: EgressPolicy | None = None` to `__init__`; store `self.policy = policy`; before `httpx.get` at line 25, extract host from URL and call `self.policy.require(host, "openalex search")` if `self.policy` is not None
2. In `crossref.py`: same pattern — add `policy` param, store it, call `self.policy.require(host, "crossref search")` before `httpx.get` at line 24

Acceptance criteria (measurable):
- `OpenAlexProvider.__init__` accepts `policy: EgressPolicy | None = None`
- `CrossrefProvider.__init__` accepts `policy: EgressPolicy | None = None`
- Before each `httpx.get`, host is extracted via `urlparse(url).hostname` and `self.policy.require(host, "...")` is called when `self.policy` is not None
- Under LOCAL_ONLY, `self.policy.require("api.openalex.org", ...)` raises `RuntimeError`
- Under HYBRID/ONLINE, `self.policy.require(...)` passes (allows all hosts)
- Existing constructors `OpenAlexProvider(timeout=timeout)` still work (policy defaults to None)
- Scoped command: `.venv/bin/python -m pytest tests/unit/ -k "openalex or crossref or academic" -v` passes

Tests that must exist and fail without the fix:
- A test that constructs `OpenAlexProvider(policy=EgressPolicy("LOCAL_ONLY"))` and calls `search()` — should raise `RuntimeError` before making network call
- Same for `CrossrefProvider`

Commands that must pass (scoped): `.venv/bin/python -m pytest tests/unit/ -k "openalex or crossref or academic" -v`

## 4. Ownership
WRITE-SET (may edit):
- `src/research_engine/providers/academic/openalex.py`
- `src/research_engine/providers/academic/crossref.py`
READ-ONLY: everything else
FORBIDDEN: `src/research_engine/providers/academic/arxiv.py`, `semantic_scholar.py` (owned by W2-IMPL-07), `src/research_engine/core/orchestrator.py` (owned by W2-IMPL-12)

Need something outside? Post `NEED`; report `DEFERRED-DEPENDENCY`.

## 5. Parallel siblings this wave
| Agent | Task | Owns | Contracts it changes |
|---|---|---|---|
| W2-IMPL-05 | C09 part A (router.build_provider) | providers/llm/router.py | `build_provider` gains `policy` param |
| W2-IMPL-07 | C09 part C (arxiv, semantic_scholar) | providers/academic/arxiv.py, semantic_scholar.py | Same pattern as your task |
| W2-IMPL-08 | C09 part D (duckduckgo) | providers/search/duckduckgo.py | Same pattern |
| W2-IMPL-09 | C09 part E (ollama, openai_compat) | providers/llm/ollama.py, openai_compat.py | Same pattern |
| W2-IMPL-10 | C09 part E (embeddings) | providers/embeddings/base.py | Same pattern |
| W2-IMPL-11 | C09 part F (fetching) | pipeline/fetching.py | `DocumentFetcher` uses `EgressPolicy` |
| W2-IMPL-12 | C09 part G (orchestrator) | core/orchestrator.py | Passes `policy` to your constructors in `build_default_registry` |

Known interactions: W2-IMPL-12 (orchestrator.py) will pass `policy=policy` to `OpenAlexProvider(timeout=timeout, policy=policy)` and `CrossrefProvider(timeout=timeout, policy=policy)`. Your constructors MUST accept `policy` keyword argument. Use `policy: EgressPolicy | None = None` default so existing callers without `policy` don't break. W2-IMPL-05 changes `build_provider` but that doesn't affect academic providers (they're constructed directly in `build_default_registry`, not via `build_provider`). You cannot see their uncommitted work.

## 6. Skip list and known traps
Already fixed (don't redo): `core/http_policy.py` `EgressPolicy` is complete; `build_default_registry` returns empty registry under LOCAL_ONLY
False leads: don't modify `build_default_registry` (owned by W2-IMPL-12); don't add network call in tests (use offline fakes or assert `RuntimeError` is raised before any `httpx.get`)
Flaky/pre-existing failures: none identified at baseline
Gotchas: Extract host from URL using `from urllib.parse import urlparse; urlparse(url).hostname`. The `BASE` constant is `https://api.openalex.org` or `https://api.crossref.org` — host extraction from the full URL is more robust than hardcoding.

## 7. Environment and tests
Scoped commands: `.venv/bin/python -m pytest tests/unit/ -k "openalex or crossref or academic" -v`
Unique test resources: none needed (offline — assert RuntimeError before any network call)
Do NOT: full suite, container restarts, shared-DB migrations, fixed ports, live network calls

## 8. Deliverables
Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w2-impl/W2-IMPL-06-T-006.md
Commits: code first, then report (docs-only), trailers: Task / Agent / Wave / Report
Final message (≤ 8 lines): STATUS | agent | task | report path | commit SHAs | blockers

## 9. Role-specific notes
- Implementer: `self.policy.require(host, "openalex search")` raises `RuntimeError` under LOCAL_ONLY for non-loopback hosts. When `self.policy is None` (default), skip the check — backward compatibility. Test by constructing with `EgressPolicy("LOCAL_ONLY")` and verifying `RuntimeError` is raised before `httpx.get` is called.
