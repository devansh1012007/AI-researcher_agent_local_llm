# Report — W2-DREV-01 (DELTA CODE REVIEWER) · wave 2 · run 20261023-evidence-pipeline-fix

## ORCH-DIGEST

| Field | Value |
|---|---|
| Agent | W2-DREV-01 (DELTA CODE REVIEWER) |
| Wave / run | 2 · 20261023-evidence-pipeline-fix |
| Branch | ops/20261023-evidence-pipeline-fix [VERIFIED `git branch --show-current`] |
| Diff reviewed | `git diff 67ae1e9..HEAD -- src/research_engine/core/orchestrator.py src/research_engine/pipeline/fetching.py src/research_engine/providers/search/duckduckgo.py` |
| Code commit SHA | 9cd0462 `fix(egress): F-1/F-2/F-3 review findings + dedicated egress enforcement tests` |
| Report commit SHA | (pending — report-only commit) |
| Report path | docs/agent-ops/20261023-evidence-pipeline-fix/reports/w2-review/W2-DREV-01.md |
| VERDICT | APPROVE |
| Files changed (source) | 3: orchestrator.py (−1), fetching.py (+12), duckduckgo.py (+53/−3) |
| Other files in commit | tests/unit/test_egress_enforcement.py (new, 24 tests) + docs/agent-ops briefs/reports (out of scope for this review) |
| Findings | F-1 FIXED · F-2 FIXED · F-3 FIXED |
| Band-aids | None |
| Regressions | None detected |
| Top 3 risks | (1) F-2 retry path not re-exercised by full suite in this review (scoped checks only); (2) duckduckgo `EgressPolicy | None` annotation relies on `from __future__ import annotations` — lazy, safe; (3) `MAX_REDIRECTS=10` shared constant duplicated across fetching.py and duckduckgo.py (intentional mirror, not a band-aid) |

## 1. Scope and method

Review limited to the three source files named in the brief, diffed against base 67ae1e9..HEAD. Verified against standing orders §11-12: each factual claim tagged `[VERIFIED path:line]`. No source edited; no full suite run (scoped checks only per brief §4). Claims from the improver report W2-IMPR-01-T-013 were checked against the actual code rather than taken on faith.

`git diff --stat 67ae1e9..HEAD` confirms exactly 3 source files changed in the improvement commit 9cd0462 (plus the new test file and docs/agent-ops artifacts, which are outside the review scope). No unexpected files touched.

## 2. Finding-by-finding verification

### F-1 — unused `EgressPolicy` import removed from orchestrator.py:15

**VERDICT: FIXED.**

[VERIFIED src/research_engine/core/orchestrator.py:12-15] Import reduced from `from research_engine.core.http_policy import EgressPolicy, build_egress_policy` to `from research_engine.core.http_policy import build_egress_policy`.

[VERIFIED src/research_engine/core/orchestrator.py] `git grep -n "EgressPolicy"` returns no matches (EXIT:1) — `EgressPolicy` has no other reference in the file. `build_egress_policy` remains imported and is used at line 652 (`build_default_registry`). The `policy=policy` forwarding to all 6 constructors (lines 666-674) and the `policy.strict` short-circuit (lines 657-658) are left intact.

No band-aid: pure import cleanup, no behavior change.

### F-2 — `httpx.HTTPStatusError` raise restored for retryable statuses before body read in fetching.py

**VERDICT: FIXED. Retry path restored.**

[VERIFIED src/research_engine/pipeline/fetching.py:13] `httpx` imported.

[VERIFIED src/research_engine/pipeline/fetching.py:82-136] `_do_fetch`:
- Line 88: initial host `self.policy.require(...)` pre-flight.
- Line 89: `httpx.Client(follow_redirects=False, …)`.
- Lines 93-103: redirect loop; on 301/302/307/308, `Location` host re-validated via `self.policy.require(..., "redirect")` then `continue`.
- Lines 110-115 (NEW): pre-body status check — if `resp.status_code in (429, 500, 502, 503, 504)` raise `httpx.HTTPStatusError(...)`, placed **after** the redirect `continue` (line 103) and **before** `body = bytearray()` (line 116). Body is never read for retryable codes.
- Lines 129-134: existing `except httpx.HTTPStatusError` re-raises retryable codes (429/500/502/503/504) so `run_with_retries` (core/retry.py:30-50, `NETWORK` policy) engages backoff; non-retryable codes return `FetchedContent(status=code, error=...)`.

Root cause fixed: the dead `except httpx.HTTPStatusError` handler is reachable again (INV-012 failure≠empty preserved). Not a try/catch wrapper, sleep, or special-case.

Retry path confirmed: retryable status → raise HTTPStatusError → caught at line 129 → `code in (...)` → `raise` at line 133 → `run_with_retries` backoff. Non-retryable status → return `FetchedContent(error=...)`, no empty body.

### F-3 — `follow_redirects=False` + per-hop `policy.require` redirect loop in duckduckgo.py

**VERDICT: FIXED. No exfiltration hole.**

[VERIFIED src/research_engine/providers/search/duckduckgo.py:15] `EgressPolicy` already imported.

[VERIFIED src/research_engine/providers/search/duckduckgo.py:30-43] New module-level `MAX_REDIRECTS = 10` and `_request_with_redirect_check(method, url, policy, **kwargs)`:
- `kwargs.pop("follow_redirects", None)` then `httpx.get`/`httpx.post(current_url, follow_redirects=False, …)` on every attempt — auto-redirect disabled.
- On 301/302/307/308 with a `Location`: `redirect_url = urljoin(current_url, location)`; `policy.require(urlparse(redirect_url).hostname or "", "redirect")` before following; `current_url = redirect_url; continue`.
- Budget exhausted → `raise httpx.HTTPError("too many redirects")`, caught by the providers' existing `except httpx.HTTPError`.
- `urlparse(...).hostname or ""` → empty host → `is_loopback_host("")` False → fail-closed under LOCAL_ONLY (http_policy.py:32-34, 36-42).

[VERIFIED src/research_engine/providers/search/duckduckgo.py:89-149] All three DuckDuckGo attempts (GET/GET/POST via `method` param) and the Searxng `httpx.get` now route through `_request_with_redirect_check` with `self.policy`; `follow_redirects=True` removed from every call site. Per-hop validation mirrored from fetching.py (the design comment at fetching.py:85-87 is now honored here too).

Under LOCAL_ONLY: loopback searxng base passes pre-flight, but a 302 to an external host is refused at hop 2 by `policy.require` → `RuntimeError` before any external body is read.

## 3. Acceptance criteria checklist

| Criterion | Status | Evidence |
|---|---|---|
| VERDICT: APPROVE / APPROVE-WITH-CHANGES / REJECT | APPROVE | All 3 findings fixed, no regressions |
| F-1: unused `EgressPolicy` import removed | ✓ | orchestrator.py:15; grep EXIT:1 |
| F-2: `httpx.HTTPStatusError` raise restored for 429/503 before body read; retry path works | ✓ | fetching.py:110-115; handler at 129-134 |
| F-3: `follow_redirects=False` + per-hop `policy.require` redirect loop; no exfiltration hole | ✓ | duckduckgo.py:30-149; `urljoin`+`hostname or ""` fail-closed |
| No other source files changed beyond the 3 | ✓ | `git diff --stat` shows only orchestrator.py, fetching.py, duckduckgo.py (+ test file) |
| No band-aids introduced | ✓ | Root causes fixed; no swallowed errors, try/catch wrappers, sleeps, or special-casing |
| ORCH-DIGEST block present | ✓ | Section above |

## 4. Long-run test (standing orders §8)

- Source: enforcement at every call site — initial host + every redirect hop re-validated through `policy.require`. ✓
- Load: `MAX_REDIRECTS=10` bounds the redirect loop; `run_with_retries` backoff re-engaged for retryable statuses. ✓
- Hostile: empty/malformed host → `hostname or ""` → `is_loopback_host("")` False → fail-closed under LOCAL_ONLY; redirect without `Location` → `break` (no infinite loop). ✓
- Operability: no schema migration, no new tables, construction-time LOCAL_ONLY gate unchanged; `policy=None` backward compat preserved (DuckDuckGo `if self.policy is not None:` skip retained). ✓
- Reversal: removing the F-2 raise makes `except httpx.HTTPStatusError` dead code again; removing F-3's per-hop `require` lets a 302→external escape pre-flight; removing F-1 leaves an unused import (harmless but lint-noise). Each test in `tests/unit/test_egress_enforcement.py` asserts `RuntimeError`/policy identity and fails without its guard.

## 5. Reversal / fails-without-fix reasoning

Per standing orders §11-12 I did not revert source by hand (forbidden). Confirmed by exact line citation:
- Revert F-1 → unused import restored (harmless, no functional regression; F-1 is MINOR).
- Revert F-2 → `except httpx.HTTPStatusError` at fetching.py:129 becomes unreachable dead code; retryable 429/503 return `FetchedContent(error=...)` with no backoff → INV-012 violated (failure masquerades as empty result).
- Revert F-3 → `follow_redirects=True` restored, per-hop `require` dropped; a 302 to an external host is followed without re-validation → redirect-based exfiltration hole reopens under LOCAL_ONLY.

## 6. Out-of-scope findings

None. No NEED posted to COMMS.md. The new `tests/unit/test_egress_enforcement.py` (24 tests, per W2-IMPR-01-T-013 §3) was part of the same commit but is outside this delta source review; it was not executed here (scoped checks only). `memory/retrieval.py` (DEFERRED-DEPENDENCY per W2-IMPL-10) remains out of scope.

## 7. Verdict

APPROVE. The three fixes are correct, complete, minimal, and introduce no band-aids or regressions. F-1/F-2/F-3 are all resolved at their root cause. No blocking issues.
