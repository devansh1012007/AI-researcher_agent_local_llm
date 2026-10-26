# Report — W1-REV-02 (TEST REVIEWER) · wave 1 · run 20261023-evidence-pipeline-fix

## ORCH-DIGEST

| Field | Value |
|---|---|
| Agent | W1-REV-02 (TEST REVIEWER) |
| Wave | 1 · run 20261023-evidence-pipeline-fix |
| Task | Test quality review of Wave 1 test diff `cd6b948..HEAD` |
| Report path | docs/agent-ops/20261023-evidence-pipeline-fix/reports/w1-review/W1-REV-02.md |
| Files reviewed (test diff only) | tests/evaluation/test_eval_framework.py (+30 lines, 1 test); tests/unit/test_local_only_gating.py (new, +71 lines, 5 tests) |
| Source diff reviewed | None (read-only; cross-checked impl reports + source) |
| Related implementer reports | W1-IMPL-01-T-001.md (C18), W1-IMPL-04-T-004.md (W6) |
| Scoped test result | [RAN `python -m pytest tests/evaluation/test_eval_framework.py tests/unit/test_local_only_gating.py -v` -> 7 passed, 7.49s] [RAN again -> 7 passed, 8.43s] — deterministic, no flakiness |
| VERDICT | APPROVE-WITH-CHANGES |
| Blockers | None |
| Commit SHAs | None (read-only; report-only docs commit pending) |

**Summary sentence:** Both test files are sound, behavior-focused, non-over-mocked, deterministic/isolated, and each test fails without its fix (reversal confirmed — C18 empirically by the implementer, W6 by airtight logic). All acceptance criteria are met. The one material gap is a P1 missing edge case for C18 (rejections present but no duplicates — the most discriminating scenario for the `duplicate_rate`/`rejected_ratio` mislabeling bug), plus P2/P3 env-override/boundary cases for W6. Existing tests are approved; the "WITH-CHANGES" is the additive P1 coverage (recommended before final sign-off) and the P2/P3 list.

---

## 1. Method and scope

Per brief §2 (blind-pass first) I read the test diff `git diff cd6b948..HEAD -- tests/evaluation/test_eval_framework.py tests/unit/test_local_only_gating.py` BEFORE any implementer report. The diff is **pure test addition**: 101 insertions, 0 deletions, 0 source changes. I then cross-checked the implementer reports (W1-IMPL-01-T-001, W1-IMPL-04-T-004) against the source:
- [VERIFIED src/research_engine/core/config.py:139,165-206] `SecurityConfig.local_only` default `False`, wired into `PlatformConfig.effective_environment()` (checked before mode mapping; unknown-mode fail-closed preserved).
- [VERIFIED src/research_engine/core/http_policy.py:23,47] `EgressPolicy.strict = environment == "LOCAL_ONLY"`; `build_egress_policy(cfg)` reads `cfg.platform.effective_environment()`.
- [VERIFIED src/research_engine/core/orchestrator.py:650-658] `build_default_registry()` returns empty registry when `policy.strict`.
- [VERIFIED evals/metrics/eval_metrics.py:75] post-fix `s.duplicate_rate = repos.evidence.duplicate_ratio(project_id)`; `rejected_evidence_ratio` (lines 73-74) unchanged, reports rejection independently.
- [VERIFIED src/research_engine/storage/repositories.py:186-206] `rejected_ratio()` = REJECTED/total over ALL evidence; `duplicate_ratio()` = duplicate quote-hashes among ACCEPTED (status!='REJECTED'), sorted by iteration.
- [VERIFIED src/research_engine/models/evidence.py:36-38] `document_id=""`, `source_id=""`, `chunk_id=""` defaults — the C18 test's `repos.evidence.save(Evidence(...))` without those fields is valid.
- [VERIFIED tests/conftest.py:40-49] `cfg` fixture calls `AppConfig.load()` (reads CWD `gar.yaml`); W6 gating tests construct `AppConfig(...)` directly, so they are isolated from ambient `gar.yaml`.
- [READ COMMS.md lines 1-37] last line read: W1-IMPL-04 DONE line (2026-10-24T14:20:13Z). No WAVE-START directive relevant to my task; no NEED posted to me.

Claims are tagged `[VERIFIED path:line]`, `[RAN <cmd> -> <result>]`, `[ASSUMED]`, or `[UNKNOWN]` per standing orders §12.

---

## 2. Per-test assessment

### 2.1 `tests/evaluation/test_eval_framework.py::test_duplicate_rate_uses_duplicate_ratio_not_rejection` (C18)

| Criterion | Assessment | Evidence |
|---|---|---|
| Asserts behavior (not implementation) | YES | Asserts `score_project(...).duplicate_rate == duplicate_ratio(pid)` and `!= rejected_ratio(pid)` — outcome-level, through the real `score_project` function. |
| Fails without the fix (reversal) | YES — empirically confirmed pre-fix by implementer [W1-IMPL-01 §4 step 3]; re-confirmed by me running post-fix [7 passed] | Without fix, line 75 = `rejected_ratio` → `duplicate_rate = 0.0` (no rejections in fixture); test asserts `== 1/3` → `0.0 == 0.333` → FAIL. Also `!= rejected_ratio` → `0.0 != 0.0` → FAIL. Reversal is airtight. |
| Deterministic / isolated | YES | `tmp_path` SQLite DB per test; no network, no LLM, no RNG; 3 fixed evidence rows. [RAN twice -> 7 passed both times, identical.] |
| Over-mocked | NO | Zero mocks; real `Database` + `Repositories` + real `score_project`. Tests the real boundary. |
| Covers changed lines/branches | YES | Directly pins eval_metrics.py:75 call site (`duplicate_ratio` vs `rejected_ratio`). Covers the `accepted` branch of `duplicate_ratio` (3 accepted rows, 1 duplicate). |
| Error paths / boundaries | PARTIAL | Covers "accepted + duplicate, no rejections". Does NOT cover "rejections present, no duplicates" (the most discriminating case — see §6 P1). Empty project not tested (ratios coincide there, low value). |

**Fixture arithmetic (independently verified):**
- ev1 "alpha beta gamma" iter1 (first occurrence → not dup), ev2 "alpha beta gamma" iter2 (same quote-hash → dup), ev3 "delta epsilon zeta" iter3 (not dup).
- `rejected_ratio(pid)` = 0 REJECTED / 3 total = `0.0`.
- `duplicate_ratio(pid)` = 1 dup / 3 accepted = `1/3`.
- Post-fix `s.duplicate_rate` = `duplicate_ratio` = `1/3`. Test: `1/3 == 1/3` ✓, `1/3 != 0.0` ✓.

**Verdict per test:** PASS — correct, necessary, sufficient for the call-site regression.

### 2.2 `tests/unit/test_local_only_gating.py` (W6) — 5 tests

| Test | Asserts behavior? | Fails w/o fix? | Deterministic/isolated? | Over-mocked? | Assessment |
|---|---|---|---|---|---|
| `test_local_only_forces_local_only` (mode=online, local_only=True) | YES (`effective_environment() == "LOCAL_ONLY"`) | YES — without wiring: online → ONLINE ≠ LOCAL_ONLY → FAIL | YES (direct `AppConfig`, no YAML) | NO (caplog only unused here) | PASS |
| `test_local_only_forces_local_only_even_in_local_mode` (mode=local, local_only=True) | YES | YES — without wiring: local → HYBRID ≠ LOCAL_ONLY → FAIL | YES | NO | PASS |
| `test_local_only_default_preserves_hybrid` (default `AppConfig()`) | YES (`local_only is False`, env == HYBRID) | YES — if default reverted to True: AppConfig() → LOCAL_ONLY ≠ HYBRID → FAIL (also breaks `test_every_leg_resolves_or_is_explicitly_optional`) | YES | NO | PASS — guards against darkening the default install |
| `test_unknown_mode_resolves_to_local_only` | YES (env == LOCAL_ONLY + error logged) | YES — if unknown-mode fail-closed removed: unknown → ONLINE/HYBRID/KeyError ≠ LOCAL_ONLY → FAIL | YES | NO (caplog for ERROR) | PASS |
| `test_local_only_registry_is_empty` | YES (empty registry, `get_any` None for web+4 academic) | YES — without wiring: strict=False → registry populated → `get_any` not None → FAIL | YES (direct cfg; providers constructed but not invoked) | NO | PASS — pins the privacy S2 endpoint |

**Reversal logic (airtight, no source edit needed):**
- Wiring removed: `local_only=True` + mode online/local → falls to mode mapping → ONLINE/HYBRID → `strict=False` → `build_default_registry` populates providers → `test_local_only_registry_is_empty` FAILS; and env ≠ LOCAL_ONLY → forcing tests FAIL.
- Default reverted to True: `AppConfig()` → `local_only=True` → LOCAL_ONLY ≠ HYBRID → `test_local_only_default_preserves_hybrid` FAILS (and `test_every_leg_resolves_or_is_explicitly_optional` FAILS).

**Verdict per test:** PASS — all five are correct, behavior-focused, non-over-mocked, deterministic, isolated, and each fails without its fix.

---

## 3. Coverage of changed lines/branches

**C18 (eval_metrics.py:75):** The test covers exactly the changed call site (`duplicate_ratio` vs `rejected_ratio`) and the `accepted`-only branch of `duplicate_ratio`. Branch coverage of `duplicate_ratio` internals: empty-accepted (`return 0.0`) NOT tested (low value — ratios coincide at 0.0); REJECTED rows excluded NOT tested. The `rejected_evidence_ratio` line (73-74) is deliberately unchanged and not asserted as duplicate — correct.

**W6 (config.py + orchestrator/http_policy):** Tests cover `effective_environment()` branches: `local_only=True` override (online + local), `local_only=False` default (HYBRID), unknown-mode fail-closed + error log. They cover `build_default_registry` empty-registry under `policy.strict`. They do NOT cover `privacy_mode=True` (pre-existing, orthogonal), `web_provider="none"` offline path, or env-override `GAR_PLATFORM__SECURITY__LOCAL_ONLY=true`.

Error-path coverage: W6 covers the unknown-mode error log. C18 covers no error path (none exists in the changed call site — correct).

Boundary coverage: C18 boundary is the ratio inequality (rejected_ratio=0 vs duplicate_ratio=1/3) — well chosen. W6 boundary is local_only True/False × mode — well chosen.

---

## 4. Mutation thinking

Plausible bugs (mutations) targeting the two changed areas, and whether the tests catch each:

| # | Hypothetical mutation | Caught by which test? | Verdict |
|---|---|---|---|
| M-a | Revert eval_metrics.py:75 to `rejected_ratio(project_id)` (W1-IMPL-03's M-19) | `test_duplicate_rate_uses_duplicate_ratio_not_rejection` — `duplicate_rate` becomes 0.0 ≠ 1/3, and `!= rejected_ratio` (`0.0 != 0.0`) fails | DETECTED |
| M-b | Delete line 75 (`duplicate_rate` stays 0.0 default) | Same test — `0.0 == 1/3` fails | DETECTED |
| M-c | Call `duplicate_ratio("wrong_pid")` → 0.0 | Same test — `0.0 == 1/3` fails | DETECTED |
| M-d | Swap assignments: `s.duplicate_rate = rejected_ratio`; `s.rejected_evidence_ratio = duplicate_ratio` | Same test — `duplicate_rate` = 0.0 ≠ 1/3, and `!= rejected_ratio` (`0.0 != 0.0`) fails | DETECTED |
| M-e | Remove `local_only` check from `effective_environment()` | `test_local_only_forces_local_only` (online → ONLINE) and `test_local_only_registry_is_empty` (registry populated) | DETECTED |
| M-f | Revert `SecurityConfig.local_only` default to `True` | `test_local_only_default_preserves_hybrid` (AppConfig() → LOCAL_ONLY ≠ HYBRID); also breaks `test_every_leg_resolves_or_is_explicitly_optional` | DETECTED |
| M-g | Check `local_only` AFTER mode mapping (mode wins) | NOT caught by current W6 tests (both online→ONLINE→LOCAL_ONLY and local→HYBRID→LOCAL_ONLY still yield LOCAL_ONLY); end result identical for tested inputs. Low-risk (non-functional: only logging/order differs). | NOT DETECTED (benign) |
| M-h | `EgressPolicy.strict = environment != "LOCAL_ONLY"` (inverted) | `test_local_only_registry_is_empty` — registry populated under LOCAL_ONLY → `get_any` not None → FAIL | DETECTED (if http_policy in scope; it's not, but the endpoint test would catch the effect) |
| M-i | Unknown mode returns ONLINE instead of LOCAL_ONLY (drop fail-closed) | `test_unknown_mode_resolves_to_local_only` (env ≠ LOCAL_ONLY + no error) → FAIL | DETECTED |
| M-j | Return HYBRID instead of LOCAL_ONLY when local_only=True | `test_local_only_forces_local_only` → FAIL | DETECTED |

**Coverage conclusion:** All high-impact mutations (M-a..M-f, M-h..M-j) are detected. M-g is benign/non-functional. The mutation gate's M-19 (revert line 75) is detected by the C18 test — consistent with W1-IMPL-01 §6.

---

## 5. Flakiness evidence (repeated runs)

[RAN `python -m pytest tests/evaluation/test_eval_framework.py tests/unit/test_local_only_gating.py -v` → 7 passed in 7.49s]
[RAN again → 7 passed in 8.43s]

Identical results, no ordering dependence, no randomness, no network/LLM. Each test uses `tmp_path` (isolated DB) or constructs config directly (no ambient `gar.yaml` read — see §1, conftest `cfg` fixture is separate). No shared state, no sleep/retry. **Flakiness: none observed; risk very low.**

---

## 6. Missing edge cases (prioritized P1/P2/P3, with case tables)

The existing tests meet all acceptance criteria and pass reversal. The following are **coverage-strengthening** recommendations, not defects. P1 is the only one that materially affects the core bug's detectability.

### 6.1 C18 — `test_duplicate_rate_uses_duplicate_ratio_not_rejection`

| P | Missing case | Why it matters | Discriminates |
|---|---|---|---|
| P1 | **Rejections present, NO duplicates**: e.g. 3 evidence rows, 1 REJECTED, 2 accepted with distinct quotes. `rejected_ratio = 1/3`, `duplicate_ratio = 0.0`. Assert `duplicate_rate == 0.0` and `!= rejected_ratio`. | This is the MOST discriminating scenario for the exact bug (mislabeled rejection rate as duplicate rate). The current fixture has zero rejections, so a buggy implementation that only misbehaves when rejections exist would slip through. | Catches call-site returning rejected_ratio whenever any rejection exists. |
| P2 | Empty project (no evidence): `duplicate_ratio == 0.0`, `rejected_ratio == 0.0` (coincide — low value). | Confirms no ZeroDivision / crash on empty. | Robustness. |
| P2 | REJECTED evidence carrying a duplicate quote: excluded from `duplicate_ratio` (accepted-only). | Confirms REJECTED rows don't inflate duplicate pressure. | Correctness of `duplicate_ratio` boundary. |
| P3 | Two duplicates same iteration (ordering nondeterminism): `duplicate_ratio` sorts by iteration; same-iteration dups depend on DB row order. | Confirms stable behavior. | Edge of `duplicate_ratio` internals (out of call-site scope). |

### 6.2 W6 — `test_local_only_gating.py`

| P | Missing case | Why it matters |
|---|---|---|
| P2 | **Env override** `GAR_PLATFORM__SECURITY__LOCAL_ONLY=true` → `effective_environment() == LOCAL_ONLY`. | Confirms the env-override path (`apply_env_overrides`) reaches `local_only`. Operators may use env instead of YAML. |
| P2 | `local_only=True` + `mode=offline` → LOCAL_ONLY (redundant but should not error). | Confirms no conflict between offline mode and local_only. |
| P3 | `privacy_mode=True` + `local_only=False` → LOCAL_ONLY (privacy takes precedence). | Pre-existing behavior, orthogonal to this change; regression guard. |
| P3 | Case-insensitive mode ("OFFLINE", "Online") → correct mapping via `.lower()`. | `effective_environment()` uses `.lower()`; worth a regression guard. |
| P3 | `build_default_registry` with `local_only=True` AND `web_provider="none"` → empty registry (already empty path). | Belt-and-braces for the offline×local_only intersection. |

### 6.3 Changed behavior without tests

None flagged. Both behavior changes (C18 call-site source; W6 `local_only` wiring + default False) have corresponding tests. The `rejected_evidence_ratio` line is unchanged (correctly not retested). `gar.yaml` already sets `local_only: true` (operator opt-in requires no config change — noted in W1-IMPL-04 §7, no test needed because `AppConfig.load()` path is covered by existing `test_an_unconfigured_provider_is_never_a_failure` via the `cfg` fixture).

---

## 7. Cross-check with W1-REV-01 (code reviewer)

- W1-REV-01 owns `eval_metrics.py`, `mutation_check.py`, `config.py`, docs. My test review is consistent with their code scope: C18's test pins `eval_metrics.py:75` (their change); W6's tests pin `config.py` `effective_environment`/`local_only` default (their change).
- No test touches `scripts/mutation_check.py` (W1-IMPL-03 owns M-19). M-19 (revert eval_metrics.py:75) is detected by the C18 test — the mutation gate and the test reinforce each other.
- Disjoint file sets per brief §5 — no conflicts. W1-IMPL-04's default change (`True → False`) is exercised by `test_local_only_default_preserves_hybrid`; the existing `test_every_leg_resolves_or_is_explicitly_optional` (passed, [RAN by implementer]) confirms the default install is not darkened.

---

## 8. Verdict and required changes

**VERDICT: APPROVE-WITH-CHANGES**

- **APPROVED as-is:** All 7 tests (C18 ×1, W6 ×5) are correct, behavior-focused, non-over-mocked, deterministic, isolated, and each fails without its fix (reversal confirmed). All acceptance criteria met. No flakiness. No changed behavior is untested.
- **WITH-CHANGES (additive coverage, not defects):** Before final sign-off, add the **P1 C18 case** ("rejections present, no duplicates") — it is the single most discriminating scenario for the exact bug and is currently absent. Implement the P2/P3 W6 cases (env override, offline×local_only, privacy precedence, case-insensitive mode) as capacity allows.

These changes are strictly additive; they do not alter any existing test or source.

---

## 9. Open items / uncertainty

- W6 reversal was confirmed by airtight logic (no source edit permitted); the implementer did not empirically run pre-fix for W6 (fix applied first, per their report §5). Logic is sufficient: removing the `local_only` check yields ONLINE/HYBRID for tested modes, which fails the forcing tests. [ASSUMED — logically airtight, not empirically re-run by me.]
- M-19 detection is confirmed logically (C18 test is the exact discriminator); I did not run `scripts/mutation_check.py` (forbidden: full-gate tool, and M-19 is W1-IMPL-03's uncommitted work). [UNKNOWN — not executed by me.]
- `http_policy.py:23` `strict` logic cross-checked via grep + implementer report; central to W6 reversal but not in my write-set. [VERIFIED via source grep + W1-IMPL-04 §2.]

---

## 10. Sign-off conditions

1. Implementer adds P1 C18 case (rejections present, no duplicates) → re-run scoped pytest (expect 8 passed).
2. (Optional, capacity permitting) Implementer adds P2/P3 W6 cases.
3. Orchestrator runs `scripts/mutation_check.py` to confirm M-19 DETECTED (W1-IMPL-03 scope).
4. No source changes required from me; report committed as docs-only per standing orders §15/#28.
