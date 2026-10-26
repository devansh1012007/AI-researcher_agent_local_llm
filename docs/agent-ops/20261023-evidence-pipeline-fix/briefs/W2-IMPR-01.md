# Brief — W2-IMPR-01 (IMPROVER) · wave 2 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Address Wave 2 review findings F-1, F-2, F-3 (code) and the BLOCKER test gap (C09 egress enforcement has no committed tests verifying `policy.require()` blocks non-loopback under LOCAL_ONLY at any enforcement point). Fix code and add tests.
Your role: improvement agent. You may edit source files owned by W2 agents (to fix review findings) and create new test files.

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§15 improvement step, §3 No-Band-Aid doctrine)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md
4. docs/agent-ops/20261023-evidence-pipeline-fix/01-work-ledger.md (Wave 2)
5. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/report-improvement.md
6. Code reviewer report: reports/w2-review/W2-REV-01.md (read findings F-1, F-2, F-3 in full)
7. Test reviewer report: reports/w2-review/W2-REV-02.md (read the test gap and P1 missing edge cases)
8. COMMS.md from the last WAVE-START
9. Source files to fix: src/research_engine/core/orchestrator.py:15, src/research_engine/pipeline/fetching.py:82-124, src/research_engine/providers/search/duckduckgo.py:60-115
10. http_policy.py: src/research_engine/core/http_policy.py (EgressPolicy contract)

## 3. Task and acceptance criteria
Task: Address every W2-REV-01 and W2-REV-02 finding:

**F-1 (MINOR) — orchestrator.py:15:** Remove unused `EgressPolicy` import. Change `from research_engine.core.http_policy import EgressPolicy, build_egress_policy` to `from research_engine.core.http_policy import build_egress_policy`.

**F-2 (MAJOR) — fetching.py:82-124:** Restore 429/503 retry path. The pre-change code manually raised `httpx.HTTPStatusError` for `resp.status_code in (429, 503)`, which the `except httpx.HTTPStatusError` handler caught to trigger `run_with_retries` backoff. The new code removed that manual raise and uses `follow_redirects=False` with no `raise_for_status()`, making `except httpx.HTTPStatusError` [fetching.py:117] unreachable dead code. Fix: restore a pre-body status check that raises `httpx.HTTPStatusError` for retryable status codes (429, 500, 502, 503, 504) before reading the body, OR remove the dead `except` block and document the intentional drop.

**F-3 (MAJOR) — duckduckgo.py:60-115:** Set `follow_redirects=False` on DuckDuckGoProvider's `httpx.get`/`httpx.post` and SearxngProvider's `httpx.get`. Add a manual redirect loop with per-hop `policy.require(urlparse(redirect_url).hostname, …)` mirroring fetching.py [fetching.py:93-103], bounded by `MAX_REDIRECTS`. Under LOCAL_ONLY, a self-hosted searxng on loopback base must NOT be able to exfiltrate via 302 to external host.

**BLOCKER (test gap):** Add `tests/unit/test_egress_enforcement.py` with tests for every enforcement point (P1 from W2-REV-02 §7):
- openalex, crossref, arxiv, semantic_scholar: `provider(policy=EgressPolicy("LOCAL_ONLY")).search()` → `RuntimeError` before network; `policy=None` works
- duckduckgo: GET + POST under LOCAL_ONLY → RuntimeError; policy=None works
- searxng: same under LOCAL_ONLY → RuntimeError
- ollama: complete() + is_available() under LOCAL_ONLY → RuntimeError
- openai_compat: same
- embeddings: embed() + is_available() under LOCAL_ONLY → RuntimeError
- DocumentFetcher: initial URL under LOCAL_ONLY → RuntimeError; 302-to-external refused at hop 2; follow_redirects=False
- ModelRouter: `for_role(role).policy == build_egress_policy(app_cfg)`; `build_provider(cfg)` backward compat
- build_default_registry: forwards `policy=policy` to all 6 constructors

Acceptance criteria:
- All 3 code findings (F-1, F-2, F-3) FIXED
- New test file `tests/unit/test_egress_enforcement.py` created with ≥ 10 tests covering all enforcement points
- `pytest tests/unit/test_egress_enforcement.py -v` passes
- `pytest tests/invariants/test_search_failure_semantics.py -v` still passes (14 passed)
- `pytest tests/evaluation/test_eval_framework.py -v` still passes (no regression from conftest pin)
- Each new test confirmed to fail without its fix (reversal) — document in report
- Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w2-improve/W2-IMPR-01-T-013.md
- All dispositions: FIXED / REJECTED-with-evidence / DEFERRED-with-reason

## 4. Ownership
WRITE-SET (may edit):
- `src/research_engine/core/orchestrator.py` (F-1: unused import)
- `src/research_engine/pipeline/fetching.py` (F-2: retry path)
- `src/research_engine/providers/search/duckduckgo.py` (F-3: redirect validation)
- `tests/unit/test_egress_enforcement.py` (NEW: dedicated egress tests)
READ-ONLY: everything else
FORBIDDEN: other W2 agent files (router.py, academic providers, ollama/openai_compat, embeddings/base.py)

## 5. Parallel siblings
None — sole improvement agent for Wave 2.

Known interactions: Your fixes touch files owned by W2-IMPL-11 (fetching.py), W2-IMPL-12 (orchestrator.py), W2-IMPL-08 (duckduckgo.py). As the improvement step, you are authorized to edit them to address review findings. Keep their existing changes intact; only fix the flagged issues.

## 6. Skip list and known traps
- Don't remove the `policy=policy` forwarding from orchestrator.py (only remove the unused `EgressPolicy` import)
- Don't change `follow_redirects=False` in fetching.py (already correct — F-2 is about the dead except block, not the redirect flag)
- For duckduckgo.py F-3: mirror fetching.py's redirect loop pattern exactly (urljoin, per-hop require, MAX_REDIRECTS bound)
- For F-2: restore the manual `httpx.HTTPStatusError` raise for 429/503 before reading the body — don't just delete the except block
- The `policy is not None` guard is the designed backward-compat contract — don't remove it

## 7. Environment and tests
Scoped commands: `pytest tests/unit/test_egress_enforcement.py -v`, `pytest tests/invariants/test_search_failure_semantics.py -v`, `pytest tests/evaluation/test_eval_framework.py -v`
Do NOT: full suite, container restarts, shared-DB migrations, fixed ports

## 8. Deliverables
Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w2-improve/W2-IMPR-01-T-013.md
Commits: code first, then report (docs-only), trailers: Task / Agent / Wave / Report
Final message (≤ 8 lines): STATUS | agent | task | report path | commit SHAs | blockers

## 9. Role-specific notes
- Improver: address every BLOCKER and MAJOR (F-2, F-3) and MINOR (F-1). Each finding ends FIXED/REJECTED-with-evidence/DEFERRED-with-reason. Improve code AND tests. Record dispositions in the report. Answer the long-run test for each fix.
