# Brief — W2-IMPL-09 (IMPL) · wave 2 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Route `httpx.post`/`httpx.get` calls in `providers/llm/ollama.py` and `providers/llm/openai_compat.py` through `EgressPolicy`. This is C09 part E — LLM providers must refuse non-loopback hosts under LOCAL_ONLY at every outbound request.
Why this matters: LLM providers make outbound HTTP calls to local/remote models. Under LOCAL_ONLY, these must be refused unless loopback.

Your role: implementer.

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§11 testing philosophy, §12 data/concurrency/security)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md (commands, baseline, hotspots)
4. Plan: docs/plans/2026-10-22-evidence-pipeline-and-analyst-review.md — items C09, C23
5. Investigation findings: `ollama.py:29` `httpx.post(f"{base}/api/chat", ...)`; `:39` `httpx.get(f"{base}/api/tags", timeout=2.0)` (in `is_available()`); `openai_compat.py:27` `httpx.post(f"{base}/chat/completions", ...)`; these are constructed via `build_provider(role_cfg)` from `ModelRouter.for_role` (W2-IMPL-05 will pass `policy`); `OllamaProvider(cfg)` and `OpenAICompatibleProvider(cfg)` take `LLMRoleConfig`
6. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/report-implementation.md
7. COMMS.md from the last WAVE-START

## 3. Task and acceptance criteria
Task T-009 (C09 part E):
1. In `ollama.py`: import `build_egress_policy` from `core.http_policy`; add `policy: EgressPolicy | None = None` to `OllamaProvider.__init__`; store `self.policy = policy`; before `httpx.post` at line 29 and `httpx.get` at line 39, extract host and call `self.policy.require(host, "ollama chat")` / `self.policy.require(host, "ollama tags")` if `self.policy` is not None
2. In `openai_compat.py`: same pattern — add `policy` param, store it, call `self.policy.require(host, "openai_compat chat")` before `httpx.post` at line 27; `LlamaCppProvider` extends `OpenAICompatibleProvider` so it inherits

Acceptance criteria (measurable):
- `OllamaProvider.__init__` accepts `policy: EgressPolicy | None = None`
- `OpenAICompatibleProvider.__init__` accepts `policy: EgressPolicy | None = None`
- Before each `httpx.post`/`httpx.get`, host extracted, `self.policy.require(host, "...")` called when `self.policy` is not None
- Under LOCAL_ONLY, `self.policy.require("localhost", ...)` passes (loopback allowed); non-loopback raises `RuntimeError`
- Existing constructors `OllamaProvider(cfg)`, `OpenAICompatibleProvider(cfg)` still work (policy defaults to None)
- `build_provider(cfg, policy)` from W2-IMPL-05 passes policy to these constructors
- Scoped command: `.venv/bin/python -m pytest tests/unit/ -k "ollama or openai or llm" -v` passes

Tests that must exist and fail without the fix:
- Test constructing with `EgressPolicy("LOCAL_ONLY")` and calling chat — non-loopback host raises `RuntimeError`

Commands that must pass (scoped): `.venv/bin/python -m pytest tests/unit/ -k "ollama or openai or llm" -v`

## 4. Ownership
WRITE-SET (may edit):
- `src/research_engine/providers/llm/ollama.py`
- `src/research_engine/providers/llm/openai_compat.py`
READ-ONLY: everything else
FORBIDDEN: `src/research_engine/providers/llm/router.py` (owned by W2-IMPL-05)

Need something outside? Post `NEED`; report `DEFERRED-DEPENDENCY`.

## 5. Parallel siblings this wave
| Agent | Task | Owns | Contracts it changes |
|---|---|---|---|
| W2-IMPL-05 | C09 part A (router.build_provider) | providers/llm/router.py | `build_provider(cfg, policy)` passes policy to your constructors |
| W2-IMPL-06 | C09 part B (openalex, crossref) | providers/academic/ | Same pattern |
| W2-IMPL-07 | C09 part C (arxiv, semantic_scholar) | providers/academic/ | Same pattern |
| W2-IMPL-08 | C09 part D (duckduckgo) | providers/search/ | Same pattern |
| W2-IMPL-10 | C09 part E (embeddings) | providers/embeddings/ | Same pattern |
| W2-IMPL-11 | C09 part F (fetching) | pipeline/fetching.py | `DocumentFetcher` uses `EgressPolicy` |
| W2-IMPL-12 | C09 part G (orchestrator) | core/orchestrator.py | Not directly — LLM providers go through `build_provider` |

Known interactions: W2-IMPL-05's `build_provider(cfg, policy)` will call `OllamaProvider(cfg, policy=policy)` and `OpenAICompatibleProvider(cfg, policy=policy)`. Your constructors MUST accept `policy` keyword argument. Use `policy: EgressPolicy | None = None` default so existing `OllamaProvider(cfg)` calls still work. You cannot see their uncommitted work.

## 6. Skip list and known traps
Already fixed: `core/http_policy.py` complete; `build_provider` signature change is W2-IMPL-05's job
False leads: don't modify `router.py` (W2-IMPL-05's job); don't modify `build_default_registry` (LLM providers aren't registered there)
Flaky/pre-existing failures: none
Gotchas: `ollama.py:39` `httpx.get(f"{base}/api/tags", ...)` is in `is_available()` — needs `require()` too. `openai_compat.py` `LlamaCppProvider` extends `OpenAICompatibleProvider` — inherits `__init__`, no change needed.

## 7. Environment and tests
Scoped commands: `.venv/bin/python -m pytest tests/unit/ -k "ollama or openai or llm" -v`
Unique test resources: none needed
Do NOT: full suite, container restarts, shared-DB migrations, fixed ports, live network calls

## 8. Deliverables
Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w2-impl/W2-IMPL-09-T-009.md
Commits: code first, then report (docs-only), trailers: Task / Agent / Wave / Report
Final message (≤ 8 lines): STATUS | agent | task | report path | commit SHAs | blockers

## 9. Role-specific notes
- Implementer: When `self.policy is None`, skip `require()`. Both `chat` (post) and `tags`/`/` (get) call sites need the check. `LlamaCppProvider` inherits from `OpenAICompatibleProvider` so it gets the policy enforcement for free.
