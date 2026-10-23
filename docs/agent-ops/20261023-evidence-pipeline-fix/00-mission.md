# Mission — 20261023-evidence-pipeline-fix

## 1. Scope (what we are fixing)

Remaining open issues from Stages 1–5 of `docs/plans/2026-10-22-evidence-pipeline-and-analyst-review.md` (implemented at commit `cd6b948`, but with gaps found by verification):

| Priority | Issue | Summary | State |
|---|---|---|---|
| P0 | C09 | Route all 12+ direct `httpx` call sites through `EgressPolicy`; add `policy` param to `router.build_provider`; manual per-hop redirect validation in `fetching.py` | Partial — module + construction gating exist; zero request-time enforcement |
| P0 | W4 | Fix sandbox guard rebindable write-root (`experiments/runner.py:37`); add override-write regression test | Not done — `_ALLOWED_WRITE_ROOT` still a rebindable module global |
| P1 | C18 | Fix `duplicate_rate` wiring in `eval_metrics.py:75` to use true `duplicate_ratio` | Partial — `eval_metrics.py:75` sets `rejected_ratio`, not true duplicate ratio |
| P1 | C19 | Add `INV-029` row to `docs/invariants.md`; update `docs/service-boundaries.md` with review operation | Not done — INV-029 missing; service-boundaries.md missing review op |
| P2 | W5 | Add ULID mutation to `scripts/mutation_check.py` | Not done — M-1..M-18 exist; none target `core/ids.py` |
| P2 | W6 | Wire `local_only` field (currently dead at `core/config.py:139`); add dedicated LOCAL_ONLY gating test | Not done — field defined but never read; no gating test |
| P2 | W7-W10 | P1/P2/P3 batch: unknown provider hard fail, dedicated templates, conformance harness, property layer, etc. | Not done — waves W7-W10 open per FIX_PLAN.md §7 |

Out of scope for this run: W7-W10 batch (P1/P2/P3 items beyond W6), phase-7 branch merge, any schema migration, any change to `SCHEMA_VERSION`.

## 2. Baseline (measured before any change)

- `pytest`: 378 passed, 1 skipped, ~113s (from prior session)
- `scripts/mutation_check.py`: M-1..M-18 all DETECTED, exit 0
- `scripts/reaudit.py`: 14/14 fixed
- `git status`: clean tree, on `main`, up to date with `origin/main`
- HEAD: `cd6b948` "Add resilient installation script and initial evaluation results"

Pre-existing failures: none identified from the baseline above.

## 3. Git safety

- `git status --porcelain`: clean (no uncommitted tracked changes)
- Branch created: `ops/20261023-evidence-pipeline-fix` (at preflight)
- BASE_SHA: `cd6b948`
- Remote: `origin` → `https://github.com/devansh1012007/AI-researcher_agent_local_llm.git` (no push/merge unless user asks)

## 4. Commands (from AGENTS.md)

- Full suite: `.venv/bin/python -m pytest` (offline, timeout=120s per test)
- Targeted: `.venv/bin/python -m pytest tests/<area> -k <pattern>`
- Mutation: `.venv/bin/python scripts/mutation_check.py`
- Reaudit: `.venv/bin/python scripts/reaudit.py`
- Packaging: `.venv/bin/python scripts/check_dist.py`
- Python venv: `.venv/bin/python` (no `python3 -m venv` — no ensurepip on this machine)
- Do NOT add `-q` twice (suppresses pytest summary)

## 5. Hotspots (single-writer files / contracts)

| Hotspot | Reason | Single writer |
|---|---|---|
| `src/research_engine/core/http_policy.py` | EgressPolicy module — C09 depends on it | Wave 2 agent only |
| `src/research_engine/providers/llm/router.py` | `build_provider` signature changes (adds policy param) | Wave 2 agent only |
| `src/research_engine/pipeline/fetching.py` | `DocumentFetcher.fetch` redirect handling — C09 | Wave 2 agent only |
| `src/research_engine/core/config.py` | `effective_environment()` + `local_only` field — W6 | Wave 1 agent W1-A4 only |
| `scripts/mutation_check.py` | MUTATIONS list — W5 adds M-19 | Wave 1 agent W1-A3 only |
| `evals/metrics/eval_metrics.py` | line 75 `duplicate_rate` — C18 | Wave 1 agent W1-A1 only |
| `docs/invariants.md` | INV table — C19 adds INV-029 | Wave 1 agent W1-A2 only |
| `docs/service-boundaries.md` | Canonical operations list — C19 | Wave 1 agent W1-A2 only |
| `experiments/runner.py` | `_SANDBOX_GUARD` — W4 | Wave 3 agent only |

## 6. Assumptions (A-nnn)

A-001: `core/ids.py` ULID implementation is correct (verified: monotonic, Crockford base32, 26 chars, seed_counter deleted).
A-002: `core/http_policy.py` EgressPolicy module is correct as designed; gap is only that no call site consults it at request time.
A-003: `repositories.py:193-204` has a working `duplicate_ratio()` method (verified).
A-004: `eval_metrics.py:75` mis-wires `duplicate_rate` = `rejected_ratio`; fix is to call `duplicate_ratio()` instead.
A-005: No schema migration needed for any of these changes (review_decisions table already exists from stage 4; no new tables/columns).

## 7. Run folder

`docs/agent-ops/20261023-evidence-pipeline-fix/` — all agent output lives here.
