# Work ledger — 20261023-evidence-pipeline-fix

Orchestrator-owned; source of truth for resume. Updated at every wave boundary.

## Plan coverage

| Plan item | Summary | Disposition |
|---|---|---|
| C09 | Route all httpx call sites through EgressPolicy; router.build_provider policy param; fetching.py redirect validation | W1 (partial → W2 completion) |
| W4 | Sandbox guard rebindable write-root; override-write regression test | W3 |
| C18 | Fix duplicate_rate wiring in eval_metrics.py:75 | W1-A1 |
| C19 | Add INV-029 row; update service-boundaries.md | W1-A2 |
| W5 | Add ULID mutation to mutation_check.py | W1-A3 |
| W6 | Wire local_only field; add LOCAL_ONLY gating test | W1-A4 |
| W7-W10 | P1/P2/P3 batch | Deferred — out of scope for this run |

## Tasks

| Task | Plan items | Domain | Class | Root cause (1 line) | Write-set | Contract-set | Depends on | Wave | Agent | Status | Code commits | Report |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T-001 | C18 | evals/metrics | SURFACE | `eval_metrics.py:75` sets `duplicate_rate = rejected_ratio`, not true `duplicate_ratio` | `evals/metrics/eval_metrics.py` | `EvalScores.duplicate_rate` semantics | — | W1 | W1-IMPL-01 | pending | | |
| T-002 | C19 | docs | SURFACE | INV-029 missing from invariants table; review op missing from canonical ops list | `docs/invariants.md`, `docs/service-boundaries.md` | INV table, service-boundaries ops list | — | W1 | W1-IMPL-02 | pending | | |
| T-003 | W5 | scripts/mutation_check | SURFACE | No ULID mutation; M-1..M-18 don't cover `core/ids.py` | `scripts/mutation_check.py` | MUTATIONS list | T-001 (mutation harness pattern known) | W1 | W1-IMPL-03 | pending | | |
| T-004 | W6 | core/config | SURFACE | `local_only` field defined but never read; no LOCAL_ONLY gating test | `src/research_engine/core/config.py`, new test file | `effective_environment()` contract | — | W1 | W1-IMPL-04 | pending | | |
| T-005 | C09 part A | providers/llm/router.py | SURFACE | `build_provider` takes no `policy` param | `src/research_engine/providers/llm/router.py` | `build_provider(cfg, policy)` signature | — | W2 | W2-IMPL-05 | pending | | |
| T-006 | C09 part B | providers/academic/* | SURFACE | 4 academic `httpx.get` sites don't consult EgressPolicy | `providers/academic/openalex.py`, `crossref.py`, `arxiv.py`, `semantic_scholar.py` | None (internal call sites) | T-005 | W2 | W2-IMPL-06 | pending | | |
| T-007 | C09 part C | providers/search/duckduckgo.py | SURFACE | 3 `httpx.get/post` sites don't consult EgressPolicy | `providers/search/duckduckgo.py` | None | T-005 | W2 | W2-IMPL-07 | pending | | |
| T-008 | C09 part D | providers/llm/ollama.py, openai_compat.py | SURFACE | 3 `httpx.post/get` sites don't consult EgressPolicy | `providers/llm/ollama.py`, `providers/llm/openai_compat.py` | None | T-005 | W2 | W2-IMPL-08 | pending | | |
| T-009 | C09 part E | providers/embeddings/base.py | SURFACE | 4 `httpx.post/get` sites don't consult EgressPolicy | `providers/embeddings/base.py` | None | T-005 | W2 | W2-IMPL-09 | pending | | |
| T-010 | C09 part F | pipeline/fetching.py | SURFACE | `httpx.Client(follow_redirects=True)` bypasses per-hop host validation | `pipeline/fetching.py` | None | T-005 | W2 | W2-IMPL-10 | pending | | |
| T-011 | C09 part G | core/orchestrator.py | SURFACE | `build_default_registry` doesn't pass EgressPolicy into provider construction | `core/orchestrator.py` | `build_default_registry` internals | T-005 | W2 | W2-IMPL-11 | pending | | |
| T-012 | W4 | experiments/runner.py | SURFACE | `_ALLOWED_WRITE_ROOT` rebindable module global in sandbox guard | `experiments/runner.py`, new test | Sandbox guard contract | — | W3 | W3-IMPL-12 | pending | | |
| T-013 | W4 | tests/experiments/ or tests/security/ | SURFACE | No override-write regression test exists | new test file | None | T-012 | W3 | W3-IMPL-13 | pending | | |

## Waves

### Wave 1 — Small issues (4 agents, parallel)
- WAVE_BASE_SHA: <to be set at dispatch>
- Agents: W1-IMPL-01 (T-001), W1-IMPL-02 (T-002), W1-IMPL-03 (T-003), W1-IMPL-04 (T-004)
- Ownership file: ownership/W1.tsv
- Pre-mortem: All four tasks touch disjoint files; no conflicts expected. Only shared resource is `scripts/mutation_check.py` (T-003) — no other agent touches it. Risk: T-004 `effective_environment()` change could affect provider registration tests; mitigated by T-004 only adding `local_only` as an additional fail-closed condition.
- Gate results: <pending>
- Review findings → dispositions: <pending>
- Review/improve cycles used: 0/2
- Status: pending dispatch

### Wave 2 — C09 egress enforcement (8 agents, parallel)
- WAVE_BASE_SHA: <to be set at dispatch>
- Agents: W2-IMPL-05..11 (T-005..T-011)
- Ownership file: ownership/W2.tsv
- Pre-mortem: T-005 changes `build_provider` signature (contract change). All other W2 agents depend on T-005's new `policy` param but do NOT call `build_provider` directly — they add `policy.allows()/require()` inside their own provider files. Risk: if T-005's `policy` param default isn't `None`-safe, existing callers of `build_provider` (only `ModelRouter.for_role`) break. Mitigation: `policy: EgressPolicy | None = None` default; `ModelRouter` passes the policy.
- Gate results: <pending>
- Review findings → dispositions: <pending>
- Review/improve cycles used: 0/2
- Status: pending dispatch

### Wave 3 — W4 sandbox guard (2 agents, parallel)
- WAVE_BASE_SHA: <to be set at dispatch>
- Agents: W3-IMPL-12 (T-012), W3-IMPL-13 (T-013)
- Ownership file: ownership/W3.tsv
- Pre-mortem: T-012 rewrites the sandbox guard; T-013 adds a test that exercises it. Risk: T-013's test may not run without the shared env (needs `exec()` sandbox); mark NOT-RUN if needed.
- Gate results: <pending>
- Review findings → dispositions: <pending>
- Review/improve cycles used: 0/2
- Status: pending dispatch

### Wave 4 — Verification & independent review (1 reviewer agent)
- WAVE_BASE_SHA: <to be set at dispatch>
- Agent: W4-REV-01 (independent review of complete diff)
- Gate: full pytest + mutation_check + reaudit
- Status: pending dispatch

### Deep dives
None in this run — all tasks are SURFACE class.

### Deferred / open items
- W7-W10 batch (P1/P2/P3): unknown provider hard fail, dedicated templates, conformance harness, property layer, silent except blocks, assert-for-runtime, dead code purge, doc drift, events observability, P3-1..P3-9 metric honesty. Deferred because out of scope for this run (user confirmed W7-W10 not in this batch).

### Out-of-plan discoveries
None yet.

### Assumptions → see 00-mission.md §6
