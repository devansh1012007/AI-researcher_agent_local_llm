# Report — W2-REV-01 (CODE REVIEWER) · wave 2 · run 20261023-evidence-pipeline-fix

Branch: `ops/20261023-evidence-pipeline-fix` (verified `git branch --show-current`). BASE_SHA: `29112d1`. HEAD: `df9f254`.

Blind pass performed per brief §3 item 6 and standing orders: I read `git diff 29112d1..HEAD -- <11 files>` in full and inspected each file in context BEFORE reading any implementer report. All source is READ-ONLY; this report is the only write.

## ORCH-DIGEST

| Field | Value |
|---|---|
| Agent | W2-REV-01 |
| Task | Independent code review of Wave 2 C09 diff (11 provider/source files) |
| Report | docs/agent-ops/20261023-evidence-pipeline-fix/reports/w2-review/W2-REV-01.md |
| Commit SHAs reviewed | a6c6309 (T-005/router), c3ed87e (T-006/openalex+crossref), 73f98f1 (T-007/arxiv+semantic_scholar), 46e8c21 (T-008/duckduckgo), 9b10175 (T-009/ollama+openai_compat), f1300ab (T-010/embeddings), ba7922b (T-011/fetching), c63c410 (T-012/orchestrator) |
| Diff size | 11 files, +158/−37 |
| Verdict | APPROVE-WITH-CHANGES |
| Required fixes (DO NOW) | F-1 (orchestrator unused import), F-2 (fetching dead HTTPStatusError / rate-limit regression), F-3 (duckduckgo+searxng follow_redirects=True bypasses per-hop validation — redirect exfiltration hole via self-hosted searxng under LOCAL_ONLY) |
| Top 3 risks | F-3 redirect-based exfiltration via searxng loopback base under LOCAL_ONLY; F-2 loss of 429/503 retry/backoff in DocumentFetcher; unimplemented dedicated egress unit tests (NEED posted by implementers, tests/ outside write-set) |
| Not run (per brief §7) | full pytest, mutation_check.py, reaudit.py, check_dist.py — scoped git checks only; implementer test claims treated as [ASSUMED] |

## 1. Scope and method

Reviewed diff: `git diff 29112d1..HEAD -- src/research_engine/core/orchestrator.py src/research_engine/pipeline/fetching.py src/research_engine/providers/llm/router.py src/research_engine/providers/llm/ollama.py src/research_engine/providers/llm/openai_compat.py src/research_engine/providers/search/duckduckgo.py src/research_engine/providers/embeddings/base.py src/research_engine/providers/academic/openalex.py src/research_engine/providers/academic/crossref.py src/research_engine/providers/academic/arxiv.py src/research_engine/providers/academic/semantic_scholar.py`.

Contract context (read-only): `src/research_engine/core/http_policy.py` (`EgressPolicy.allows/require`, `build_egress_policy`, strict ⇔ LOCAL_ONLY) and `src/research_engine/core/config.py` (`is_loopback_host`: True only for loopback IPv4/IPv6/localhost; everything else False → `require` raises `RuntimeError`).

Required-reading order per brief §2: STANDING-ORDERS, AGENTS.md §15/§3, 00-mission.md, 01-work-ledger.md, review-code.md (template absent from repo — noted), the blind-pass diff, implementer reports W2-IMPL-05..12, COMMS.md, http_policy.py. All read.

## 2. The diff at a glance

C09 = route all direct `httpx` call sites through `EgressPolicy`; add `policy` param to `router.build_provider`; manual per-hop redirect validation in `fetching.py`.

| File | What changed |
|---|---|
| `core/orchestrator.py` | `build_default_registry` builds `policy = build_egress_policy(cfg)` (already existed), imports `EgressPolicy` (unused — see F-1), forwards `policy=policy` to all 6 provider constructors; `policy.strict` early return (empty registry under LOCAL_ONLY) unchanged. |
| `pipeline/fetching.py` | `DocumentFetcher.__init__` builds `self.policy = build_egress_policy(cfg)`; `follow_redirects=True` → `follow_redirects=False`; validates initial host before first `stream`; manual redirect loop (`MAX_REDIRECTS=10`) re-validates each `Location` host via `policy.require` before following. |
| `providers/llm/router.py` | `build_provider(cfg, policy=None)`; `ModelRouter.__init__` builds `self.policy = build_egress_policy(app_cfg)`; `for_role` passes `self.policy`; policy delivered via `setattr(provider, "policy", policy)` (constructor injection rejected because `MockProvider` doesn't accept `policy`). |
| `providers/llm/ollama.py`, `openai_compat.py` | `__init__(..., policy=None)`; `_require(host, what)` helper (skip when `None`); `require` before `httpx.post` (chat) and `httpx.get` (tags). `LlamaCppProvider` inherits. |
| `providers/search/duckduckgo.py` | `DuckDuckGoProvider` + `SearxngProvider` accept `policy=None`; `require(base_host)` before each of the 3 `httpx` call sites. **`follow_redirects=True` retained on all 3 (see F-3).** |
| `providers/embeddings/base.py` | `_host_of` fail-closed helper; both providers accept `policy=None`; all 4 `httpx` call sites (`embed` ×2, `is_available` ×2) gated with `require` before the call. |
| `providers/academic/openalex.py`, `crossref.py`, `arxiv.py`, `semantic_scholar.py` | Each accepts `policy=None`; `require(urlparse(url).hostname)` before its single `httpx.get`. |

## 3. Claims audit (implementer claims vs. code)

W2-IMPL-05 (T-005, router.py, a6c6309): **ACCURATE.** `build_provider(cfg: LLMRoleConfig, policy: EgressPolicy | None = None)` [router.py:32]; `ModelRouter.__init__` builds `self.policy = build_egress_policy(app_cfg)` [router.py:54]; `for_role` calls `build_provider(role_cfg, self.policy)` [router.py:61]; `EgressPolicy` is TYPE_CHECKING-only import [router.py:19-20], `build_egress_policy` runtime import [router.py:14]; `setattr` delivery [router.py:46-47]; one call site (`for_role` only) [router.py:61]; `build_provider(cfg)` with `policy=None` unchanged [router.py:32 default]. [VERIFIED router.py:1-75]

W2-IMPL-06 (T-006, openalex+crossref, c3ed87e): **ACCURATE.** Both `__init__(..., policy=None)`; `self.policy = policy`; `require(urlparse(url).hostname, "…")` before `httpx.get`; `policy=None` skips check. [VERIFIED openalex.py:24-34, crossref.py:24-35 per diff]

W2-IMPL-07 (T-007, arxiv+semantic_scholar, 73f98f1): **ACCURATE.** Same pattern; arxiv uses `urlparse(self.BASE).hostname`; semantic_scholar builds local `url` then `require(urlparse(url).hostname)`. [VERIFIED per diff]

W2-IMPL-08 (T-008, duckduckgo, 46e8c21): **PARTIALLY ACCURATE.** The 3 direct `httpx.get`/`httpx.post` call sites ARE gated with `require(base_host)` when `policy is not None` [duckduckgo.py:61-63, 66-68, 112-114 per diff]. Claim "before each httpx.get/httpx.post … require called" holds for the base URL. **INCOMPLETE:** `follow_redirects=True` is retained on all 3 call sites [duckduckgo.py:60, 65] and Searxng uses httpx's default `follow_redirects=True` [duckduckgo.py:115] — redirect targets are NOT per-hop validated (see F-3).

W2-IMPL-09 (T-009, ollama+openai_compat, 9b10175): **ACCURATE.** `_require` helper skips when `None`; gated before `httpx.post` (chat) and `httpx.get` (tags); `urlparse(base).hostname or ""` → empty host fail-closed under LOCAL_ONLY. [VERIFIED ollama.py:14-53, openai_compat.py:14-53 per diff]

W2-IMPL-10 (T-010, embeddings/base.py, f1300ab): **ACCURATE.** `_host_of` raises `RuntimeError` on unparseable host (fail-closed); all 4 call sites gated before the network call; `policy=None` skips. Correctly flags `memory/retrieval.py` as DEFERRED-DEPENDENCY (constructs these providers without `policy`, outside write-set). [VERIFIED embeddings/base.py:78-142 per diff]

W2-IMPL-11 (T-011, fetching.py, ba7922b): **PARTIALLY ACCURATE.** `self.policy = build_egress_policy(cfg)` [fetching.py:60]; initial-host `require` before first `stream` [fetching.py:88]; `follow_redirects=False` [fetching.py:89]; per-hop `require` on each 301/302/307/308 `Location` [fetching.py:99-101]; `MAX_REDIRECTS=10` bounds loop [fetching.py:62, 93]. **INACCURATE claim:** "Existing `httpx.HTTPStatusError`/`httpx.HTTPError` handling preserved unchanged" [W2-IMPL-11 §4.1] — the pre-change manual `raise httpx.HTTPStatusError("rate limited", …)` for 429/503 was removed and `raise_for_status()` is never called, so `except httpx.HTTPStatusError` [fetching.py:117] is now dead code; 429/503 retry/backoff is lost (see F-2).

W2-IMPL-12 (T-012, orchestrator.py, c63c410): **ACCURATE.** All 6 constructor calls pass `policy=policy` [orchestrator.py:666-674]; `policy.strict` early return (empty registry under LOCAL_ONLY) unchanged [orchestrator.py:657-658]; `EgressPolicy` imported but unused (F-1).

## 4. Findings

### F-1 — Unused import `EgressPolicy` in orchestrator.py (slop, minor)

- **File:line:** `src/research_engine/core/orchestrator.py:15`
- **Evidence:** `from research_engine.core.http_policy import EgressPolicy, build_egress_policy` is the only reference to `EgressPolicy` in the file (grep returned solely the import line). `build_egress_policy` is used at line 652; `EgressPolicy` itself is never referenced (no type annotation, no runtime use).
- **Severity:** Minor. No lint/format gate is configured (no ruff/flake8/mypy in pyproject.toml), so it won't break the build, but it is dead slop per AGENTS §7 ("unused config/flags/dead compatibility layers").
- **Recommended fix:** Change line 15 to `from research_engine.core.http_policy import build_egress_policy` and remove the now-unused `EgressPolicy` import.

### F-2 — Dead `except httpx.HTTPStatusError` block; 429/503 retry/backoff lost in fetching.py (behavior regression, moderate)

- **File:line:** `src/research_engine/pipeline/fetching.py:82-124` (specifically `except httpx.HTTPStatusError` at line 117, now unreachable)
- **Evidence:** Pre-change `_do_fetch` manually raised `httpx.HTTPStatusError("rate limited", …)` for `resp.status_code in (429, 503)`, which the `except httpx.HTTPStatusError` handler caught and re-raised (429/500/502/503/504) to trigger `run_with_retries` backoff. The new code (a) removed that manual raise and (b) uses `follow_redirects=False` with no `raise_for_status()`. httpx never raises `HTTPStatusError` on a plain status code, so the `except httpx.HTTPStatusError` block [fetching.py:117-122] is unreachable dead code. 429/503 now fall through to body-reading and return a `FetchedContent` with an error status — no retry, no backoff. This contradicts W2-IMPL-11's claim that HTTPStatusError handling is "preserved unchanged."
- **Severity:** Moderate. INV-012 ("failure ≠ empty") — provider failures should surface via retry machinery, not silently degrade to an error status. Not a security hole, but a genuine behavior regression.
- **Recommended fix:** Restore a pre-body status check (e.g. `if resp.status_code in (429, 500, 502, 503, 504): raise httpx.HTTPStatusError(...)`) before reading the body so the existing `except httpx.HTTPStatusError` retry path engages, or remove the dead `except httpx.HTTPStatusError` block if retry is intentionally dropped (then document it). Do not leave dead exception handling.

### F-3 — `follow_redirects=True` in duckduckgo.py + searxng.py bypasses per-hop redirect validation; redirect-based exfiltration via self-hosted searxng under LOCAL_ONLY (security gap, moderate-high)

- **File:line:** `src/research_engine/providers/search/duckduckgo.py:60, 65` (DuckDuckGo explicit `follow_redirects=True`), `src/research_engine/providers/search/duckduckgo.py:115` (Searxng, httpx default `follow_redirects=True`)
- **Evidence:** Each provider validates the **base** host once via `policy.require(urlparse(base).hostname, …)` before the first call [duckduckgo.py:61-63, 66-68, 112-114], but then httpx follows 301/302/307/308 redirects automatically to whatever `Location` names, with no per-hop `policy.require`. Under LOCAL_ONLY, DuckDuckGo's base `html.duckduckgo.com` is non-loopback → blocked at pre-flight (no redirect chain starts). However, Searxng with a loopback base URL (e.g. a self-hosted `http://127.0.0.1:8080`, a legitimate LOCAL_ONLY configuration) PASSES the loopback check, then follows redirects to ANY external/exfiltration host without validation. DuckDuckGo would have the same hole if a loopback mirror were configured.
- **Severity:** Moderate-high. Directly contradicts fetching.py's own design comment ("A pre-flight check alone is insufficient: a 302 to an external host escapes it" [fetching.py:85-87]) and W2-IMPL-11's root cause. This is an invariant gap: the redirect fix was applied to one call site (fetching.py) but not to the search providers that also follow redirects.
- **Recommended fix:** Set `follow_redirects=False` on DuckDuckGo's `httpx.get`/`httpx.post` and Searxng's `httpx.get`, then add a manual redirect loop with per-hop `policy.require(urlparse(redirect_url).hostname, …)` mirroring fetching.py [fetching.py:93-103], bounded by a `MAX_REDIRECTS` constant.

## 5. Acceptance criteria checks (brief §3)

| Check | Result | Evidence |
|---|---|---|
| `policy.require(host)` blocks non-loopback under LOCAL_ONLY | PASS | `EgressPolicy.allows` ⇒ `is_loopback_host(host)` when strict [http_policy.py:32-33]; `is_loopback_host` True only for loopback/localhost, else False [config.py:114-128] → `require` raises `RuntimeError` [http_policy.py:36-42] |
| fetching.py `follow_redirects=False` + per-hop validation prevents redirect exfiltration | PASS (for DocumentFetcher) | `follow_redirects=False` [fetching.py:89]; initial host `require` [fetching.py:88]; per-hop `require` on each 301/302/307/308 `Location` [fetching.py:99-101]; `MAX_REDIRECTS=10` [fetching.py:62, 93] |
| `build_provider(cfg, policy=None)` keeps backward compat | PASS | `policy=None` default [router.py:32]; no `setattr` when `None` [router.py:46-47]; `MockProvider(cfg)` unchanged; one call site (`for_role`) always passes non-None policy |
| orchestrator passes `policy` to ALL 6 providers | PASS | DuckDuckGo [orchestrator.py:666], Searxng [668], OpenAlex [671], Crossref [672], Arxiv [673], SemanticScholar [674] all pass `policy=policy` |

## 6. Long-run test

- **Source:** Enforcement is at the source (each provider consults `self.policy` before its own `httpx` call) — correct. Exception: F-3 means search providers' redirect targets escape source enforcement.
- **Load:** `MAX_REDIRECTS=10` bounds the fetching redirect loop [fetching.py:62, 93] — no unbounded loop. `ModelRouter` caches providers per role; `setattr` is per-construction — no per-request allocation. No concurrency hazard introduced (policy is read-only after construction).
- **Hostile input:** Malformed/empty host → `urlparse(...).hostname or ""` → `is_loopback_host("")` → False → `require` raises [fetching.py:88-89, 101; ollama.py:17-18; openai_compat.py:17-18] — fail-closed, no host injection. `urljoin` resolves relative `Location` before validation [fetching.py:99] — no open-redirect bypass in fetching.
- **Operability:** `policy=None` skip = full backward compatibility for all direct constructors; LOCAL_ONLY returns empty registry at construction [orchestrator.py:657-658]; no schema migration; no new tables.
- **Reversal:** Reverting any `self.policy.require(...)` call site lets the network call proceed under LOCAL_ONLY instead of raising `RuntimeError` — the implementers' reversal answers are correct; dedicated egress unit tests (posted as NEED by W2-IMPL-05/06/07/08/10/11) would be the regression detectors and do not yet exist [ASSUMED — tests/ outside write-set, not verified].

## 7. Band-aid hunt

- No swallowed errors: `RuntimeError` from `EgressPolicy.require` propagates out of `search()`/`_raw_complete()`/`embed()`/`is_available()` because it is not an `httpx.HTTPError`/`HTTPStatusError` and is not caught by the providers' `except` blocks — fail-closed before network [verified by inspection of each provider's try/except].
- No blanket try/catch, no sleeps/retries to mask races, no hardcoding for tests, no type/lint suppression, no failing-path-behind-flag, no single-call-site fixes where the invariant breaks at the source — EXCEPT F-2 (removed error handling) and F-3 (redirect invariant fixed at fetching.py but not at search providers).
- The `policy is not None` guard is the designed backward-compat contract (per brief convention), not a band-aid: the orchestrator/router always supply a non-None policy, so the production path is always enforced.
- No copy-paste patches: each provider implements its own `require` call (anti-slop rule was followed; no shared helper was introduced where one caller each).

## 8. Optimization pass

- **DO NOW:** F-1 (remove unused `EgressPolicy` import in orchestrator.py:15); F-2 (restore 429/503 retry path or remove dead `except httpx.HTTPStatusError` in fetching.py:117-122); F-3 (set `follow_redirects=False` + manual per-hop validation in DuckDuckGoProvider.search and SearxngProvider.search, mirroring fetching.py).
- **DO LATER:** Add dedicated egress unit tests (LOCAL_ONLY ⇒ `RuntimeError` before network; HYBRID/ONLINE ⇒ allowed; `policy=None` ⇒ skipped; redirect-refusal) — implementers posted NEED to COMMS; tests/ is outside this reviewer's write-set [standing orders §2].
- **NOT WORTH-IT:** Constructor injection for `build_provider` (rejected correctly: `MockProvider` doesn't accept `policy`); importing `EgressPolicy` at runtime in router.py (TYPE_CHECKING import is correct, zero runtime cost); gating provider construction behind `policy.strict` only (already exists, LOCAL_ONLY-only).

## 9. Verdict

**APPROVE-WITH-CHANGES.**

The C09 implementation is directionally correct and complete for all direct `httpx` call sites: every provider consults `EgressPolicy.require(host)` before its outbound call, `build_provider`/`ModelRouter`/`build_default_registry` forward the policy, `build_provider(cfg)` backward compat is preserved, `fetching.py` disables auto-redirects and validates each hop, and LOCAL_ONLY short-circuits to an empty registry at construction. None of the three findings invalidate the core enforcement mechanism.

F-1 (unused import) and F-2 (dead HTTPStatusError / lost 429-503 retry) are contained correctness/slop fixes. F-3 (search providers follow redirects without per-hop validation) is a genuine security gap: a self-hosted searxng on a loopback base under LOCAL_ONLY can exfiltrate via a 302 to an external host, directly contradicting fetching.py's stated design. All three are small, contained fixes that do not require architectural change.

The implementers' claims are largely accurate; W2-IMPL-08 and W2-IMPL-11 overstate completeness by omitting the redirect-following behavior (F-3) and the removed rate-limit handling (F-2) respectively. W2-IMPL-12 correctly documents the cross-agent dependency (arxiv accepts `policy` uncommitted; others pending) and the post-wave gate.

Blocking items for final acceptance: F-1, F-2, F-3 fixes; and the NEED-posted dedicated egress unit tests (tests/ outside write-set). `memory/retrieval.py` embedding-provider wiring remains DEFERRED-DEPENDENCY (W2-IMPL-10 flagged, per brief §6 skip list).
