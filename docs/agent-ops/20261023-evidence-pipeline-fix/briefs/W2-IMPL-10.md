# Brief — W2-IMPL-10 (IMPL) · wave 2 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Route `httpx.post`/`httpx.get` calls in `providers/embeddings/base.py` through `EgressPolicy`, and update `memory/retrieval.py` to pass a policy when constructing embedding providers. This is C09 part E — embedding providers must refuse non-loopback hosts under LOCAL_ONLY at every outbound request.
Why this matters: Embedding providers call out to ollama/openai-compatible servers. Under LOCAL_ONLY, these calls must be governed by egress policy.

Your role: implementer.

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§11 testing philosophy, §12 data/concurrency/security)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md (commands, baseline, hotspots)
4. Plan: docs/plans/2026-10-22-evidence-pipeline-and-analyst-review.md — items C09, C23
5. Investigation findings: `embeddings/base.py:77` `httpx.post(f"{self.base_url}/api/embeddings", ...)` (OllamaEmbeddingProvider.embed); `:87` `httpx.get(f"{self.base_url}/api/tags", ...)` (is_available); `:106` `httpx.post(f"{self.base_url}/embeddings", ...)` (OpenAICompatibleEmbeddingProvider.embed); `:116` `httpx.get(self.base_url, ...)` (is_available); Embedding providers constructed in `memory/retrieval.py:160-165` directly with `OllamaEmbeddingProvider(model=..., base_url=..., timeout=...)` and `OpenAICompatibleEmbeddingProvider(...)`
6. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/report-implementation.md
7. COMMS.md from the last WAVE-START

## 3. Task and acceptance criteria
Task T-010 (C09 part E):
1. In `embeddings/base.py`: import `build_egress_policy` from `core.http_policy`; add `policy: EgressPolicy | None = None` to `OllamaEmbeddingProvider.__init__` and `OpenAICompatibleEmbeddingProvider.__init__`; store `self.policy = policy`; before each `httpx.post`/`httpx.get` (lines 77, 87, 106, 116), extract host and call `self.policy.require(host, "ollama embed")` / `self.policy.require(host, "openai embed")` if `self.policy` is not None
2. In `memory/retrieval.py`: import `build_egress_policy`; build `policy = build_egress_policy(cfg)`; pass `policy=policy` to `OllamaEmbeddingProvider(...)` and `OpenAICompatibleEmbeddingProvider(...)` constructors at lines 160-165

Acceptance criteria (measurable):
- Both embedding provider `__init__` methods accept `policy: EgressPolicy | None = None`
- Before each `httpx.post`/`httpx.get`, host extracted, `self.policy.require(host, "...")` called when `self.policy` is not None
- `memory/retrieval.py` passes `policy=policy` to embedding constructors
- Under LOCAL_ONLY, non-loopback host raises `RuntimeError`
- Existing constructors without `policy` still work
- Scoped command: `.venv/bin/python -m pytest tests/unit/ -k "embed or embedding or retrieval" -v` passes

Tests that must exist and fail without the fix:
- Test constructing embedding provider with `EgressPolicy("LOCAL_ONLY")` and calling `embed()` — non-loopback raises `RuntimeError`

Commands that must pass (scoped): `.venv/bin/python -m pytest tests/unit/ -k "embed or embedding or retrieval" -v`

## 4. Ownership
WRITE-SET (may edit):
- `src/research_engine/providers/embeddings/base.py`
- `src/research_engine/memory/retrieval.py` (pass policy to constructors)
READ-ONLY: everything else
FORBIDDEN: all other files

Need something outside? Post `NEED`; report `DEFERRED-DEPENDENCY`.

## 5. Parallel siblings this wave
| Agent | Task | Owns | Contracts it changes |
|---|---|---|---|
| W2-IMPL-05 | C09 part A (router.build_provider) | providers/llm/router.py | Not directly — embeddings not via build_provider |
| W2-IMPL-06..08 | C09 parts B-D (academic, search) | providers/academic/, providers/search/ | Same pattern |
| W2-IMPL-09 | C09 part E (ollama, openai_compat LLM) | providers/llm/ | Same pattern (LLM, not embeddings) |
| W2-IMPL-11 | C09 part F (fetching) | pipeline/fetching.py | `DocumentFetcher` uses `EgressPolicy` |
| W2-IMPL-12 | C09 part G (orchestrator) | core/orchestrator.py | Not directly — embeddings constructed in memory/retrieval.py |

Known interactions: W2-IMPL-10 is responsible for both `embeddings/base.py` AND `memory/retrieval.py` (embedding construction site). No other agent touches these files. You cannot see their uncommitted work.

## 6. Skip list and known traps
Already fixed: `core/http_policy.py` complete
False leads: don't modify `build_default_registry` (embeddings aren't registered there)
Flaky/pre-existing failures: none
Gotchas: 4 call sites in `embeddings/base.py` (2 per provider class). `memory/retrieval.py` needs `from research_engine.core.http_policy import build_egress_policy` and `policy = build_egress_policy(cfg)` before the constructor calls.

## 7. Environment and tests
Scoped commands: `.venv/bin/python -m pytest tests/unit/ -k "embed or embedding or retrieval" -v`
Unique test resources: none needed
Do NOT: full suite, container restarts, shared-DB migrations, fixed ports, live network calls

## 8. Deliverables
Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w2-impl/W2-IMPL-10-T-010.md
Commits: code first, then report (docs-only), trailers: Task / Agent / Wave / Report
Final message (≤ 8 lines): STATUS | agent | task | report path | commit SHAs | blockers

## 9. Role-specific notes
- Implementer: When `self.policy is None`, skip `require()`. All 4 `httpx` call sites need the check. `memory/retrieval.py` constructs providers directly (not via `build_default_registry`), so it must build and pass its own policy.
