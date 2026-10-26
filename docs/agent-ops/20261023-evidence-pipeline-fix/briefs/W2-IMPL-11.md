# Brief — W2-IMPL-11 (IMPL) · wave 2 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Route `DocumentFetcher` through `EgressPolicy` with manual per-hop redirect validation in `pipeline/fetching.py`. This is C09 part F — document fetching must refuse non-loopback hosts under LOCAL_ONLY and must not follow redirects to external hosts.
Why this matters: `fetching.py:80` uses `httpx.Client(follow_redirects=True, ...)` — a 302 redirect to an external host escapes a pre-flight check. Manual per-hop validation is required: disable auto-redirects, check each `Location` header's host through `EgressPolicy.allows()` before following.

Your role: implementer.

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§11 testing philosophy, §12 data/concurrency/security)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md (commands, baseline, hotspots)
4. Plan: docs/plans/2026-10-22-evidence-pipeline-and-analyst-review.md — items C09, C23
5. Investigation findings: `fetching.py:51` `class DocumentFetcher` with `__init__(self, cfg, cache=None, transport=None)`; `:80` `with httpx.Client(follow_redirects=True, timeout=ncfg.timeout_seconds, headers={...}, transport=self.transport) as client:`; `:83` `with client.stream("GET", url) as resp:`; `DocumentFetcher` constructed in `documents.py:30` as `DocumentFetcher(cfg, transport=transport)`; `core/http_policy.py` `EgressPolicy.allows(host)` / `require(host)`
6. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/report-implementation.md
7. COMMS.md from the last WAVE-START

## 3. Task and acceptance criteria
Task T-011 (C09 part F):
1. In `fetching.py`: import `build_egress_policy` from `core.http_policy`; in `__init__`, build `self.policy = build_egress_policy(cfg)`; in `_do_fetch`, replace `follow_redirects=True` with `follow_redirects=False`; before `client.stream("GET", url)`, extract host from URL and call `self.policy.require(host, "document fetch")`; after each response, if status is 301/302/307/308, extract `Location` header host, call `self.policy.require(redirect_host, "redirect")`, then manually follow by making a new request to the redirect URL (with its own host check)

Acceptance criteria (measurable):
- `DocumentFetcher.__init__` builds `self.policy` from `build_egress_policy(cfg)`
- Before the initial `client.stream("GET", url)`, `self.policy.require(url_host, "document fetch")` is called
- Auto-redirects disabled (`follow_redirects=False`)
- On 301/302/307/308, redirect `Location` host is checked via `self.policy.require(redirect_host, "redirect")` before following
- Under LOCAL_ONLY, non-loopback URL raises `RuntimeError` before any network call
- Redirect to external host under LOCAL_ONLY is refused
- Existing `DocumentFetcher(cfg, transport=transport)` constructor still works
- Scoped command: `.venv/bin/python -m pytest tests/unit/ -k "fetch or fetcher or document" -v` passes

Tests that must exist and fail without the fix:
- Test constructing `DocumentFetcher(cfg_with_LOCAL_ONLY)` and calling `fetch("http://external-host.com/page")` — should raise `RuntimeError` before network call
- Test that a 302 redirect to external host under LOCAL_ONLY is refused

Commands that must pass (scoped): `.venv/bin/python -m pytest tests/unit/ -k "fetch or fetcher or document" -v`

## 4. Ownership
WRITE-SET (may edit):
- `src/research_engine/pipeline/fetching.py`
READ-ONLY: everything else
FORBIDDEN: `src/research_engine/pipeline/documents.py` (constructs DocumentFetcher but doesn't need changes — constructor signature unchanged)

Need something outside? Post `NEED`; report `DEFERRED-DEPENDENCY`.

## 5. Parallel siblings this wave
| Agent | Task | Owns | Contracts it changes |
|---|---|---|---|
| W2-IMPL-05 | C09 part A (router.build_provider) | providers/llm/router.py | Not directly |
| W2-IMPL-06..10 | C09 parts B-E (providers) | various provider files | Same pattern |
| W2-IMPL-12 | C09 part G (orchestrator) | core/orchestrator.py | `build_default_registry` — not directly related to fetching |

Known interactions: W2-IMPL-11 is the only agent touching `fetching.py`. `documents.py:30` constructs `DocumentFetcher(cfg, transport=transport)` — constructor signature unchanged, so no modification needed there. You cannot see their uncommitted work.

## 6. Skip list and known traps
Already fixed: `core/http_policy.py` complete; `EgressPolicy.allows()` / `require()` work
False leads: don't modify `documents.py` (constructor unchanged); don't use `follow_redirects=True` with a pre-flight check only — manual per-hop validation is required
Flaky/pre-existing failures: none
Gotchas: Manual redirect loop: `while resp.status_code in (301, 302, 307, 308):` extract `Location` header, check host, make new request. Track redirect count to prevent infinite loops. Host from `urlparse(url).hostname`.

## 7. Environment and tests
Scoped commands: `.venv/bin/python -m pytest tests/unit/ -k "fetch or fetcher or document" -v`
Unique test resources: none needed (use httpx MockTransport or assert RuntimeError before network call)
Do NOT: full suite, container restarts, shared-DB migrations, fixed ports, live network calls

## 8. Deliverables
Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w2-impl/W2-IMPL-11-T-011.md
Commits: code first, then report (docs-only), trailers: Task / Agent / Wave / Report
Final message (≤ 8 lines): STATUS | agent | task | report path | commit SHAs | blockers

## 9. Role-specific notes
- Implementer: The redirect loop must check EACH hop's host, not just the first. A 302 to loopback then 302 to external must be caught at the second hop. Use `resp.headers.get("location")` for the redirect URL.
