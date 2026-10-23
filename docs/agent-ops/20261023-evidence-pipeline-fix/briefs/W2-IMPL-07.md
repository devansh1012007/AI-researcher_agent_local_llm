# Brief — W2-IMPL-07 (IMPL) · wave 2 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Route `httpx.get` calls in `providers/academic/arxiv.py` and `providers/academic/semantic_scholar.py` through `EgressPolicy`. This is C09 part C — academic search providers must refuse non-loopback hosts under LOCAL_ONLY at every outbound request.
Why this matters: Same as W2-IMPL-06 — construction-time gating alone is insufficient. Each provider must enforce egress at request time.

Your role: implementer.

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§11 testing philosophy, §12 data/concurrency/security)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md (commands, baseline, hotspots)
4. Plan: docs/plans/2026-10-22-evidence-pipeline-and-analyst-review.md — items C09, C23
5. Investigation findings: `arxiv.py:29` `httpx.get(self.BASE, ...)` where `BASE = "https://export.arxiv.org/api/query"`; `semantic_scholar.py:26` `httpx.get(f"{self.BASE}/paper/search", ...)`; both raise `SearchProviderError` on failure; constructed in `build_default_registry` (`orchestrator.py:673-674`) with `ArxivProvider(timeout=timeout)`, `SemanticScholarProvider(cfg.search.semantic_scholar_api_key, timeout)`
6. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/report-implementation.md
7. COMMS.md from the last WAVE-START

## 3. Task and acceptance criteria
Task T-007 (C09 part C):
1. In `arxiv.py`: import `build_egress_policy` from `core.http_policy`; add `policy: EgressPolicy | None = None` to `__init__`; store `self.policy = policy`; before `httpx.get` at line 29, extract host and call `self.policy.require(host, "arxiv search")` if `self.policy` is not None
2. In `semantic_scholar.py`: same pattern — add `policy` param, store it, call `self.policy.require(host, "semantic_scholar search")` before `httpx.get` at line 26

Acceptance criteria (measurable):
- `ArxivProvider.__init__` accepts `policy: EgressPolicy | None = None`
- `SemanticScholarProvider.__init__` accepts `policy: EgressPolicy | None = None`
- Before each `httpx.get`, host extracted via `urlparse(url).hostname`, `self.policy.require(host, "...")` called when `self.policy` is not None
- Under LOCAL_ONLY, `self.policy.require("export.arxiv.org", ...)` raises `RuntimeError`
- Under HYBRID/ONLINE, passes
- Existing constructors `ArxivProvider(timeout=timeout)`, `SemanticScholarProvider(api_key, timeout)` still work
- Scoped command: `.venv/bin/python -m pytest tests/unit/ -k "arxiv or semantic_scholar or academic" -v` passes

Tests that must exist and fail without the fix:
- Test constructing with `EgressPolicy("LOCAL_ONLY")` and calling `search()` — should raise `RuntimeError` before network call

Commands that must pass (scoped): `.venv/bin/python -m pytest tests/unit/ -k "arxiv or semantic_scholar or academic" -v`

## 4. Ownership
WRITE-SET (may edit):
- `src/research_engine/providers/academic/arxiv.py`
- `src/research_engine/providers/academic/semantic_scholar.py`
READ-ONLY: everything else
FORBIDDEN: `src/research_engine/providers/academic/openalex.py`, `crossref.py` (owned by W2-IMPL-06), `src/research_engine/core/orchestrator.py` (owned by W2-IMPL-12)

Need something outside? Post `NEED`; report `DEFERRED-DEPENDENCY`.

## 5. Parallel siblings this wave
| Agent | Task | Owns | Contracts it changes |
|---|---|---|---|
| W2-IMPL-05 | C09 part A (router.build_provider) | providers/llm/router.py | `build_provider` gains `policy` param |
| W2-IMPL-06 | C09 part B (openalex, crossref) | providers/academic/openalex.py, crossref.py | Same pattern |
| W2-IMPL-08 | C09 part D (duckduckgo) | providers/search/duckduckgo.py | Same pattern |
| W2-IMPL-09 | C09 part E (ollama, openai_compat) | providers/llm/ollama.py, openai_compat.py | Same pattern |
| W2-IMPL-10 | C09 part E (embeddings) | providers/embeddings/base.py | Same pattern |
| W2-IMPL-11 | C09 part F (fetching) | pipeline/fetching.py | `DocumentFetcher` uses `EgressPolicy` |
| W2-IMPL-12 | C09 part G (orchestrator) | core/orchestrator.py | Passes `policy` to your constructors |

Known interactions: W2-IMPL-12 passes `policy=policy` to `ArxivProvider(timeout=timeout, policy=policy)` and `SemanticScholarProvider(api_key, timeout, policy=policy)`. Your constructors MUST accept `policy` keyword argument. Use `policy: EgressPolicy | None = None` default. You cannot see their uncommitted work.

## 6. Skip list and known traps
Already fixed: `core/http_policy.py` complete; construction-time gating works
False leads: don't modify `build_default_registry` (W2-IMPL-12's job)
Flaky/pre-existing failures: none
Gotchas: `semantic_scholar.py` has `self.BASE` — check the exact value. Host from `urlparse(full_url).hostname`.

## 7. Environment and tests
Scoped commands: `.venv/bin/python -m pytest tests/unit/ -k "arxiv or semantic_scholar or academic" -v`
Unique test resources: none needed
Do NOT: full suite, container restarts, shared-DB migrations, fixed ports, live network calls

## 8. Deliverables
Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w2-impl/W2-IMPL-07-T-007.md
Commits: code first, then report (docs-only), trailers: Task / Agent / Wave / Report
Final message (≤ 8 lines): STATUS | agent | task | report path | commit SHAs | blockers

## 9. Role-specific notes
- Implementer: When `self.policy is None`, skip the `require()` call — backward compatibility for existing constructor calls without `policy`.
