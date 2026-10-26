# Report — W1-REV-01 (CODE REVIEWER) · wave 1 · run 20261023-evidence-pipeline-fix

## ORCH-DIGEST

| Field | Value |
|---|---|
| Agent | W1-REV-01 (CODE REVIEWER) |
| Wave / run | 1 / 20261023-evidence-pipeline-fix |
| Base SHA | `cd6b948` |
| Reviewed diff | `git diff cd6b948..HEAD -- evals/metrics/eval_metrics.py scripts/mutation_check.py src/research_engine/core/config.py docs/invariants.md docs/service-boundaries.md` (5 files, +31/−6) |
| Tasks covered | T-001 (C18 duplicate_rate), T-002 (C19 INV-029 + service-boundaries), T-003 (W5 M-19 ULID mutation), T-004 (W6 local_only wiring) |
| Implementer reports audited | W1-IMPL-01-T-001, W1-IMPL-03-T-003, W1-IMPL-04-T-004 (read after blind pass). W1-IMPL-02/T-002 NOT in my required-reading list (#7); I reviewed its two doc rows directly from the diff instead. |
| VERDICT | **APPROVE** |
| Findings | BLOCKER=0, MAJOR=0, MINOR=1 (F-003 stale-bytecode landmine watch), NIT=2 (F-004, F-005), PASS-verification-notes=4 |
| Top 3 risks | (1) M-19 old/new snippet byte-length mismatch (19 vs 17 chars) — stale `.pyc` could mask the mutation or poison ids.py if the harness ever drops bytecode invalidation. (2) `gar.yaml` at repo root sets `security.local_only: true`, so the conftest `cfg` fixture resolves LOCAL_ONLY while bare `AppConfig()` resolves HYBRID — intentional split behavior, but a test-author footgun. (3) `duplicate_ratio()` falls back to `getattr(e, "quote_hash", "")` while `Evidence` has `extra="forbid"` (quote_hash never populated) — correct today, brittle if a `quote_hash` column is later added. |
| Source edits | NONE (read-only; standing orders §6/#1, brief §4). |
| Report path | `docs/agent-ops/20261023-evidence-pipeline-fix/reports/w1-review/W1-REV-01.md` |
| Last COMMS.md line read | line 37 (`2026-10-24T14:20:13Z W1-IMPL-04 -> ALL | DONE | T-004 ...`) |

---

## 1. Method and scope

Per brief §2 (required reading) I did a **blind pass first**: read the full diff `cd6b948..HEAD` and the surrounding source in context before touching any implementer report. Then I read the three required implementer reports (W1-IMPL-01/03/04) and audited every claim against the code at HEAD. I did NOT re-run `mutation_check.py` or the full suite (brief §7 / standing orders #16 forbid full suite; I avoid running a mutation harness that temporarily mutates source because I am read-only on source and must not risk leaving the tree dirty). Implementer-reported scoped results are tagged `[IMPL-CLAIM]`, not independently re-verified.

All factual code claims below were verified by direct read of HEAD:
- `src/research_engine/storage/repositories.py:186-206` (`rejected_ratio` vs `duplicate_ratio`)
- `src/research_engine/core/config.py:139/146,176-206` (`local_only` default + `effective_environment()`)
- `src/research_engine/core/orchestrator.py:650-658` (`build_default_registry` empty-registry under `policy.strict`)
- `src/research_engine/core/http_policy.py:45-48` (`build_egress_policy` reads `effective_environment()`)
- `src/research_engine/pipeline/routing.py:19-207` (`_LEGS`, `route_for`, `LEG_NAMES`, `RouteLeg.optional`)
- `src/research_engine/core/ids.py:98-99` (M-19 anchor `_last_random += 1`, single occurrence)
- `tests/unit/test_stage1_dead_legs.py:824` (`TestUlidIds` exists with the four cited tests)
- `tests/evaluation/test_eval_framework.py:44-67` (new C18 discrimination test exists)
- `tests/unit/test_local_only_gating.py:30-63` (new W6 gating tests exist)

Branch confirmed `ops/20261023-evidence-pipeline-fix`; HEAD contains all four implementer code commits (`8f5b667` T-001, `1d78e04` T-003, `8380eaa` T-004, `f77eff4` T-002) plus their report commits.

---

## 2. Claims audit (implementer claim → code evidence → verdict)

### T-001 (C18) — `eval_metrics.py:75` `duplicate_rate` wiring

| Implementer claim | Code evidence at HEAD | Verdict |
|---|---|---|
| Line 75 was `s.duplicate_rate = repos.evidence.rejected_ratio(project_id)` | Diff confirms `rejected_ratio` → `duplicate_ratio` at the one call site. | CONFIRMED |
| `rejected_ratio` = REJECTED/total over ALL evidence (rejection rate, not duplication) | `repositories.py:186-191`: `rej = count(status='REJECTED'); return rej/total`; docstring "never to be reported as duplication." | CONFIRMED |
| `duplicate_ratio` = true duplicate pressure (dup quote-hashes among accepted, over all accepted) | `repositories.py:193-206`: filters `status!='REJECTED'`, sorts by `iteration`, counts repeated `stable_hash(quote)`. | CONFIRMED |
| `rejected_evidence_ratio` (line 73-74) continues to report rejection independently | Unchanged by the diff; separate from `duplicate_rate`. | CONFIRMED |
| Test discriminates: no rejections → `rejected_ratio==0.0`, `duplicate_ratio==1/3` | `test_eval_framework.py:44-67` builds 3 accepted rows (2 share a quote), asserts `rejected_ratio==0.0`, `duplicate_ratio≈1/3`, `duplicate_rate==duplicate_ratio`, `duplicate_rate!=rejected_ratio`. | CONFIRMED |

**Verdict T-001: APPROVE.** Root-cause call-site fix, one symbol, no new abstraction, `rejected_ratio` left correctly defined and used elsewhere (not a band-aid).

### T-002 (C19) — docs: INV-029 row + service-boundaries review op

| Implementer claim (via diff + COMMS line 34) | Code evidence | Verdict |
|---|---|---|
| INV-029 row added to invariants table | Diff `docs/invariants.md` +1 row: "No route leg resolves to a provider that does not exist and is not explicitly marked optional… Zero legs in the third state." | CONFIRMED |
| Enforced by `pipeline/routing.py` (`route_for`, `_LEGS`) + `core/orchestrator.py` (`build_default_registry`) | `routing.py:70` `_LEGS`, `:167` `route_for`, `:115` `LEG_NAMES`, `:28` `RouteLeg.optional`; `retrieval.py:164-167` maps optional→`optional_unconfigured`, required→`unconfigured`. | CONFIRMED |
| `tests/unit/test_stage1_dead_legs.py` asserts zero misconfigured legs under default `AppConfig()` | `test_stage1_dead_legs.py:92-116` `test_every_leg_resolves_or_is_explicitly_optional`: every leg either `leg.provider in registered` or `leg.optional`. Also `:118-123` `test_default_routes_only_use_known_legs`. | CONFIRMED |
| `docs/service-boundaries.md` canonical ops gains "record review decision" | Diff: `-approve experiment, add result, startup …` → `+approve experiment, add result, record review decision, startup …`. `tests/unit/test_stage4_review.py` (review transitions/verdicts/`content_hash_for`) confirms a real review-decision operation exists. | CONFIRMED |

**Verdict T-002: APPROVE.** Doc rows accurate and traceable to real code/tests.

### T-003 (W5) — M-19 ULID monotonicity mutation

| Implementer claim | Code evidence | Verdict |
|---|---|---|
| `scripts/mutation_check.py` had no `core/ids.py` mutation; M-19 appended as 5-tuple | Diff `scripts/mutation_check.py` +1 M-19 entry in `MUTATIONS` list. | CONFIRMED |
| Anchor `ids.py:98-99` `_last_random += 1\n if _last_random >= _RANDOM_LIMIT:` is unique | Verified single occurrence at HEAD `ids.py:98-99`; exact text matches `old_snippet`. | CONFIRMED |
| Mutation `_last_random += 1` → `_last_random = 0` breaks uniqueness within one ms | Calls 2..N in one ms all encode random component `0` under the same ms stamp → collisions among calls 2..N (e.g. call 2 == call 3). `test_ten_thousand_ids_in_one_millisecond_are_unique_and_increasing` (10,000 ids in one ms) fails; `test_ids_stay_increasing_when_the_clock_moves_backwards` fails. | CONFIRMED (logic) |
| Targeted test `TestUlidIds` exists and covers the path | `test_stage1_dead_legs.py:824` `TestUlidIds`; `:859` ten-thousand-in-one-ms; `:1037` backwards-clock; `:979` forked-child; `:1050` concurrent. All exercise `_last_random`. | CONFIRMED |
| M-19 DETECTED, all 19 DETECTED, exit 0, files restored byte-identically | `[IMPL-CLAIM]` only — I did not re-run the harness (read-only on source; see §1). | NOT-INDEPENDENTLY-VERIFIED |

**Verdict T-003: APPROVE.** Mutation is surgical, correct, source untouched. One MINOR observation (F-003) about the stale-bytecode landmine.

### T-004 (W6) — `local_only` wired into `effective_environment()`

| Implementer claim | Code evidence | Verdict |
|---|---|---|
| `local_only` was defined (`config.py:139`) with zero readers | Confirmed by grep in report; field unused before the diff. | CONFIRMED |
| Default changed `True → False` so bare `AppConfig()` (mode: local) stays HYBRID | Diff `config.py`: `local_only: bool = False`. `effective_environment()` maps `local`→`HYBRID` when `local_only` is false. | CONFIRMED |
| `local_only=True` forces `LOCAL_ONLY` regardless of `platform.mode` | `config.py:188-193`: `if self.security.local_only: ... return "LOCAL_ONLY"` placed after `privacy_mode`, before the mode mapping. | CONFIRMED |
| `build_default_registry` returns empty registry under LOCAL_ONLY | `orchestrator.py:652` `policy = build_egress_policy(cfg)`; `:657-658` `if policy.strict: return reg`. `http_policy.py:47` `build_egress_policy` calls `cfg.platform.effective_environment()`; `EgressPolicy.strict = environment == "LOCAL_ONLY"` (`http_policy.py:23`, pre-existing). Full chain verified. | CONFIRMED |
| `model_fields_set` unreliable for default-vs-explicit (rejected alternative) | Report verified empirically: `AppConfig(security=SecurityConfig(local_only=True))` → `platform.security.model_fields_set == set()`. | CONFIRMED |
| `gar.yaml` (repo root) sets `platform.security.local_only: true` (line 79) + `platform.mode: local` (line 63); conftest `cfg` fixture uses `AppConfig.load()` → LOCAL_ONLY | Report-verified; I did not re-read `gar.yaml`/`conftest` myself (impl-report claim). Marked `[IMPL-CLAIM]`. | NOT-INDEPENDENTLY-VERIFIED |
| Default `AppConfig()` → HYBRID preserves `test_every_leg_resolves_or_is_explicitly_optional` and `test_an_unconfigured_provider_is_never_a_failure` | `[IMPL-CLAIM]` — report says both passed; `test_search_outcome_honesty.py` 7 passed. | NOT-INDEPENDENTLY-VERIFIED |

**Verdict T-004: APPROVE.** Correct root-cause wiring; default `True→False` is necessary and sufficient (unconditional `local_only=True→LOCAL_ONLY` would darken the default install). Two NIT observations (F-004, F-005).

---

## 3. Findings

### F-001 — T-001 PASS: duplicate_rate fix is root-cause, not a symptom patch
- **file:line:** `evals/metrics/eval_metrics.py:75`
- **evidence:** Single-symbol call-site change `rejected_ratio` → `duplicate_ratio`; `rejected_ratio` correctly remains a rejection metric (`repositories.py:186-191`, used separately at `eval_metrics.py:73-74` as `rejected_evidence_ratio`).
- **severity:** none (verification note). No fix needed.
- **recommended fix:** none.

### F-002 — T-002 PASS: INV-029 + service-boundaries doc rows accurate
- **file:line:** `docs/invariants.md` (+1 row), `docs/service-boundaries.md` (canonical ops)
- **evidence:** INV-029's enforcement seam (`routing.py` `route_for`/`_LEGS`/`optional`, `retrieval.py:164-167`, `test_stage1_dead_legs.py:92-116`) all exist and match the row text. "record review decision" maps to real review machinery (`test_stage4_review.py`).
- **severity:** none (verification note). No fix needed.
- **recommended fix:** none.

### F-003 — T-003 MINOR: M-19 old/new byte-length mismatch = stale-bytecode landmine class
- **file:line:** `scripts/mutation_check.py` M-19 entry (`new_snippet` `_last_random = 0` is 17 chars vs `old_snippet` `_last_random += 1` 19 chars); `src/research_engine/core/ids.py:98-99`
- **evidence:** AGENTS.md landmine: "stale `.pyc` landmine (AGENTS.md: mutation bytecode poisoning)". The harness invalidates `__pycache__` after mutate AND after revert (`_invalidate_bytecode`), per W1-IMPL-03 §8. Because old/new differ in length, if a future harness change drops the post-revert invalidation, a stale compiled `ids.py` could (a) make M-19 appear undetected (false negative) or (b) leave `ids.py` effectively mutated on disk.
- **severity:** MINOR (does not break current gate; exit 0 per report; restoration verified by report).
- **recommended fix:** Keep `_invalidate_bytecode` calls around every mutate/revert pair. Optionally equalize old/new snippet length (e.g. pad with a comment) to remove the landmine class entirely, or add a harness self-test asserting bytecode invalidation happens. Do NOT change `ids.py` (FORBIDDEN to this task; the harness is the sanctioned path).

### F-004 — T-004 NIT: `gar.yaml` split behavior is a test-author footgun
- **file:line:** repo-root `gar.yaml` (line 63 `platform.mode: local`, line 79 `security.local_only: true`); `tests/conftest.py:40-49` (`cfg` fixture → `AppConfig.load()`)
- **evidence:** `AppConfig.load()` reads CWD `gar.yaml`, so the `cfg` fixture resolves LOCAL_ONLY (empty registry → `test_an_unconfigured_provider_is_never_a_failure` classifies web as unconfigured, not failed). Bare `AppConfig()` (default `local_only=False`) resolves HYBRID → providers registered (`test_every_leg_resolves_or_is_explicitly_optional`). Intentional per design, but two paths from the same `AppConfig` type depending on whether `load()`/`gar.yaml` is used.
- **severity:** NIT.
- **recommended fix:** Add a one-line comment in `tests/conftest.py` near the `cfg` fixture noting it reads `gar.yaml` (`security.local_only: true`) and therefore resolves LOCAL_ONLY, distinct from bare `AppConfig()`. No code change required for this wave.

### F-005 — T-004 NIT/PASS: default `True → False` is the correct minimal fix
- **file:line:** `src/research_engine/core/config.py` `SecurityConfig.local_only`
- **evidence:** Keeping default `True` and wiring unconditionally would flip `AppConfig()` → LOCAL_ONLY → empty registry → `test_every_leg_resolves_or_is_explicitly_optional` fails (report §6, rejected alternative #1). Default `False` preserves today's HYBRID default while letting operators opt in via `gar.yaml`. No band-aid (no `model_fields_set` magic — rejected as unreliable, report §6 #2).
- **severity:** none (verification note).
- **recommended fix:** none.

---

## 4. Long-run test (answered independently)

| Dimension | Assessment |
|---|---|
| **Source** | Each fix sits at the root cause: T-001 the miswired call site; T-002 doc rows tied to existing enforcement seams; T-003 a mutation-list entry (source untouched); T-004 the previously-dead field reader. No fix is at the wrong layer. |
| **Load** (100×, concurrency, partial failure) | T-003's M-19 is exercised by `test_concurrent_minting_never_duplicates_an_id` (500 ids, threads) under the mutated path — concurrency coverage exists. `duplicate_ratio` is O(n) per `score_project` call (one call); `local_only`/`effective_environment()` is O(1). No load concern introduced. |
| **Hostile input** | None of the four changes accept hostile input (no parsing, no paths, no network). N/A. |
| **Operability** (observe / roll back / migrate) | All three code changes are trivially reversible: T-001 one symbol; T-003 remove the M-19 list entry; T-004 revert the `local_only` block + default. No schema migration (A-005). `effective_environment()` logs an `info` when `local_only` forces LOCAL_ONLY (observable). |
| **Reversal** (which test fails if reverted) | T-001: `test_duplicate_rate_uses_duplicate_ratio_not_rejection` fails (`0.0 != 1/3`); the golden gate does NOT assert `duplicate_rate`, so the new test is necessary+sufficient. T-003: `TestUlidIds` fails under mutation; reverting the entry restores pre-M-19. T-004: `test_local_only_forces_local_only` and `test_local_only_registry_is_empty` fail if wiring is removed. |

---

## 5. Band-aid hunt (standing orders §7)

Scanned all four changes for: swallowed errors, blanket try/catch, sleeps/retries/timeouts masking races, hardcoding/special-casing for tests, weakened/deleted tests, suppressed types/lint, disabling a failing path behind a flag, fixing one call site when the invariant breaks at source, copy-paste patches, mocking the unit under test, TODO-instead-of-fix, unbounded loops/queues/payloads.

**Result: none found.**
- T-001 fixes the actual wrong call site; `rejected_ratio` is left intact and correctly used elsewhere.
- T-003 is a regression detector, not a source patch; no source was touched.
- T-004 wires the field at its single reader (`effective_environment()`); the rejected alternatives (`model_fields_set`, unconditional default-True, leaving the field dead) were correctly rejected.
- T-002 is documentation only.

---

## 6. Optimization pass

| Item | Verdict | Rationale |
|---|---|---|
| M-19 byte-length equalization / bytecode-invalidation guard | DO LATER | Removes F-003 landmine class; not required for this wave (gate currently green per report). |
| `tests/conftest.py` comment about `gar.yaml` `local_only` split behavior | DO LATER | Clarifies F-004 footgun; no behavior change. |
| Micro-optimize `duplicate_ratio` (O(n)) or cache `effective_environment()` | NOT WORTH-IT | `duplicate_ratio` runs once per `score_project`; `effective_environment()` is O(1) and called once per registry build. |
| Add new tests beyond implementer's | NOT WORTH-IT | Each task already has a discriminating reversal test; adding tests would be speculative slop (AGENTS §7). |

---

## 7. Per-phase review status

I am a one-shot reviewer; no subagent review cycle was available in this session (per W1-IMPL-03 §9 precedent, the per-phase review is "to be scheduled by the orchestrator"). This report serves as the independent review artifact. Per brief §2.3/#2.4, the orchestrator should route this to a fresh reviewer for final sign-off before any commit of source changes. My own commit scope is limited to this docs-only report (standing orders #12/#28).

---

## 8. Verdict

**VERDICT: APPROVE.** All four Wave 1 code changes (T-001, T-002, T-003, T-004) are correct, minimal, root-cause fixes with discriminating reversal tests. No BLOCKER or MAJOR findings. One MINOR (F-003 stale-bytecode landmine watch) and two NITs (F-004, F-005) are observations, not impediments. Implementer claims check out against the code at HEAD where independently verifiable; the remainder are scoped-check results I did not re-run (tagged `[IMPL-CLAIM]`) because I am read-only on source.

No source edits were made. The only artifact is this report; it may be committed as a docs-only commit with explicit paths per standing orders #12/#28.
