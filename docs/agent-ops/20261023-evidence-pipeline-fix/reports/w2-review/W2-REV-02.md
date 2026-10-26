# Report — W2-REV-02 (TEST REVIEWER) · task T-review · wave 2 · run 20261023-evidence-pipeline-fix

## ORCH-DIGEST

| Field | Value |
|---|---|
| Agent | W2-REV-02 (TEST REVIEWER) |
| Task | Independent test quality review of Wave 2 C09 egress enforcement |
| Report | docs/agent-ops/20261023-evidence-pipeline-fix/reports/w2-review/W2-REV-02.md |
| Write-set | docs/agent-ops/20261023-evidence-pipeline-fix/reports/w2-review/W2-REV-02.md only (READ-ONLY on all source/tests) |
| Branch verified | ops/20261023-evidence-pipeline-fix (`git branch --show-current`) |
| WAVE_BASE_SHA | 29112d1 |
| Source commits reviewed | a6c6309e (T-005 router), c3ed87e (T-006 openalex/crossref), 73f98f1 (T-007 arxiv/semantic_scholar), TBD/T-008 duckduckgo, 9b10175 (T-009 ollama/openai_compat), W2-IMPL-10 embeddings/base.py, ba7922b80ab9b671f62d8e435f6c49c1b9f42bbe (T-011 fetching), c63c410 (T-012 orchestrator) |
| Test commit reviewed | tests/conftest.py (LOCAL_ONLY=false pin) |
| Scoped check run | `pytest tests/invariants/test_search_failure_semantics.py -v` → 14 passed in 1.13s [RAN, exit 0] |
| Full suite | NOT run (brief §7 / AGENTS §4 forbid) |
| mutation_check / reaudit / check_dist | NOT run (not required for test review; brief §7 scoped only) |
| Verdict | **APPROVE-WITH-CHANGES** — source changes are correct and complete; BLOCKED on missing dedicated egress enforcement tests (all 8 implementers posted NEED; tests/ outside every W2 write-set) |

---

## 1. Blind pass: test diff (read BEFORE implementer reports, per brief §3 item 6)

`git diff 29112d1..HEAD -- tests/` touches exactly ONE file:

`tests/conftest.py` — added 5 lines pinning `GAR_PLATFORM__SECURITY__LOCAL_ONLY=false` so the suite stays hermetic regardless of an ambient `gar.yaml` (AGENTS.md §3). Rationale documented inline: W2 C09 egress enforcement consults the policy on every fetch; without this pin, a developer's `gar.yaml` with `platform.security.local_only: true` would block offline tests.

**No test file was added, modified, or deleted except `tests/conftest.py`.** There is no committed regression test anywhere in `tests/` that constructs a provider with `policy=EgressPolicy("LOCAL_ONLY")` and asserts `RuntimeError` before a network call. Confirmed by grep: `EgressPolicy`, `LOCAL_ONLY`, `build_egress_policy`, `policy.require`, `.allows(` appear in tests only in `tests/conftest.py` (the env pin) and `tests/unit/test_local_only_gating.py` (W6 config wiring, construction-time empty-registry gate only — no request-time enforcement).

## 2. Source changes verified against the actual diff (all 11 files, match implementer reports 1:1)

The source diff `git diff 29112d1..HEAD -- src/` is 11 files, +158/−37. Every change matches its implementer report; no unreported or extra changes.

| File | Agent | Change (verified in diff) | Request-time `require()` under LOCAL_ONLY? |
|---|---|---|---|
| `providers/llm/router.py` | W2-IMPL-05 (T-005) | `build_provider(cfg, policy=None)`; `ModelRouter.policy = build_egress_policy(app_cfg)`; `for_role` forwards `self.policy`; post-construction `setattr(provider, "policy", policy)` when not None | Indirect (delivers policy to LLM providers) |
| `providers/academic/openalex.py` | W2-IMPL-06 (T-006) | `__init__(..., policy=None)`; `self.policy.require(urlparse(url).hostname, "openalex search")` before `httpx.get` | YES |
| `providers/academic/crossref.py` | W2-IMPL-06 (T-006) | Same pattern, `"crossref search"` | YES |
| `providers/academic/arxiv.py` | W2-IMPL-07 (T-007) | `__init__(..., policy=None)`; `require(urlparse(self.BASE).hostname, "arxiv search")` inside `try` before `httpx.get`; `RuntimeError` not caught by `except httpx.HTTPError` | YES |
| `providers/academic/semantic_scholar.py` | W2-IMPL-07 (T-007) | `__init__(api_key="", timeout=20.0, policy=None)`; `require(urlparse(url).hostname, "semantic_scholar search")` | YES |
| `providers/search/duckduckgo.py` | W2-IMPL-08 (T-008) | `DuckDuckGoProvider.__init__(timeout=15.0, policy=None)`; `SearxngProvider.__init__(base_url, timeout=15.0, policy=None)`; `require()` at 3 httpx sites (GET, POST, searxng GET) | YES (3 sites) |
| `providers/llm/ollama.py` | W2-IMPL-09 (T-009) | `__init__(cfg, policy=None)`; `_require()` helper; `require()` before `httpx.post` (chat) and `httpx.get` (tags); `RuntimeError` propagates out of `is_available` | YES (2 sites) |
| `providers/llm/openai_compat.py` | W2-IMPL-09 (T-009) | Same pattern; `LlamaCppProvider` inherits enforcement for free | YES (chat site; tags via inheritance) |
| `providers/embeddings/base.py` | W2-IMPL-10 (T-010) | `_host_of()` fail-closed helper (raises `RuntimeError` on unparseable host); `OllamaEmbeddingProvider`/`OpenAICompatibleEmbeddingProvider` `__init__(..., policy=None)`; `require()` at 4 sites (embed ×2, is_available ×2) | YES (4 sites) |
| `pipeline/fetching.py` | W2-IMPL-11 (T-011) | `self.policy = build_egress_policy(cfg)`; `follow_redirects=False`; initial-host `require()` before first `client.stream`; per-hop `require()` on `Location` for 301/302/307/308; `MAX_REDIRECTS=10`; loop-bounded; each hop re-validated | YES (initial + per-hop) |
| `core/orchestrator.py` | W2-IMPL-12 (T-012) | `build_default_registry` imports `EgressPolicy`; forwards `policy=policy` to all 6 constructor calls; `policy.strict` early return (empty registry under LOCAL_ONLY) unchanged | Wiring (construction-time) |

Key correctness observations from the diff:
- All providers use `urlparse(...).hostname` (not hardcoded `BASE`) per the brief's robustness gotcha — a future `BASE` change won't stale the guard.
- `is_loopback_host(host)` does `(host or "")`, so a `None`/unparseable hostname fails closed under LOCAL_ONLY.
- `RuntimeError` from `require()` is raised **before** any `httpx` call and is **not** caught by `except httpx.HTTPError` (INV-012 preserved: genuine transport errors still surface as `SearchProviderError`/`LLMError`; policy blocks are distinct, intentional fail-closed failures).
- `fetching.py` disables auto-redirects and re-validates each hop, so a 302 chain to an external host cannot escape the pre-flight check (the exact C09 vulnerability).
- `router.py` deliberately does NOT use constructor injection (`cls(cfg, policy=policy)`) because `MockProvider` (llm/base.py, outside every W2 write-set) rejects a `policy` kwarg; post-construction `setattr` keeps `build_provider(cfg)` with `policy=None` completely unchanged — backward compat verified in the diff.
- `fetching.py:60` declares `MAX_REDIRECTS = 10` as a class-level constant inside `__init__` body (indented under it in the diff) — functionally a module-level bound; no unbounded loop (standing orders §7).

## 3. NEED items from all eight W2 implementer reports (missing tests per provider)

Every W2 implementer (W2-IMPL-05 … W2-IMPL-12) explicitly states that dedicated acceptance-criteria egress tests are required by brief §3 but are **outside their WRITE-SET** (tests/ is read-only per brief §4 / standing orders §1), so each posted a NEED and none created them. Consolidated list:

| Implementer | Provider file(s) | Required test (per report) | Test exists? |
|---|---|---|---|
| W2-IMPL-05 (T-005) | `providers/llm/router.py` | `tests/unit/test_provider_router.py`: (a) `build_provider(cfg)` backward compat (policy=None, no `policy` attr), (b) `build_provider(cfg, policy=pol)` sets `provider.policy`, (c) `ModelRouter(app_cfg).for_role(role).policy == build_egress_policy(app_cfg)`, (d) `MockProvider` via `build_provider` does not break with `policy=None` | NO |
| W2-IMPL-06 (T-006) | `openalex.py`, `crossref.py` | `tests/unit/test_academic_egress.py`: `OpenAlexProvider(policy=EgressPolicy("LOCAL_ONLY")).search()` → `RuntimeError` before network; same for `CrossrefProvider`; HYBRID/ONLINE allowed; `policy=None` backward compat | NO |
| W2-IMPL-07 (T-007) | `arxiv.py`, `semantic_scholar.py` | Construct with `EgressPolicy("LOCAL_ONLY")`, call `search()`, expect `RuntimeError` before network (verified via `/tmp` script only, not committed) | NO |
| W2-IMPL-08 (T-008) | `duckduckgo.py` | `tests/unit/test_duckduckgo_egress.py`: `DuckDuckGoProvider(policy=EgressPolicy("LOCAL_ONLY"))` + `search()` → `RuntimeError` before network; `SearxngProvider` same; `policy=None` constructors work | NO |
| W2-IMPL-09 (T-009) | `ollama.py`, `openai_compat.py` | No dedicated provider-specific tests exist in the suite; reversal detector is a test constructing `OllamaProvider(cfg, policy=EgressPolicy("LOCAL_ONLY"))` with a remote `base_url` and calling `complete()`/`is_available()` → `RuntimeError` before network | NO |
| W2-IMPL-10 (T-010) | `embeddings/base.py` | Acceptance test: provider with `LOCAL_ONLY` + non-loopback `embed()`/`is_available()` raises `RuntimeError` before network | NO |
| W2-IMPL-11 (T-011) | `fetching.py` | `tests/unit/test_fetching_egress.py`: `DocumentFetcher(cfg_LOCAL_ONLY).fetch("http://external-host.com/page")` → `RuntimeError` before network; 302-to-external refused; per-hop re-validation; `follow_redirects=False`; constructor backward-compat | NO |
| W2-IMPL-12 (T-012) | `core/orchestrator.py` | Test asserting `build_default_registry` forwards `policy` + provider-level enforcement tests (by W2-IMPL-06..10) | NO |

**Bottom line: zero committed tests verify `policy.require()` blocks non-loopback under LOCAL_ONLY at any provider call site.** The only LOCAL_ONLY coverage is construction-time (test_local_only_gating.py: empty registry) — which is necessary but insufficient; it does not exercise request-time enforcement, per-hop redirect validation, or the `RuntimeError`-before-network contract.

## 4. Acceptance-criteria checklist: "does a test exist that verifies policy.require() blocks non-loopback under LOCAL_ONLY?"

For each provider file changed by W2:

| File | `policy.require(host)` present in source? | Dedicated LOCAL_ONLY→RuntimeError-before-network test exists? | Verdict |
|---|---|---|---|
| router.py (policy delivery) | N/A (delivers policy) | NO | MISSING |
| openalex.py | YES | NO | MISSING |
| crossref.py | YES | NO | MISSING |
| arxiv.py | YES | NO | MISSING |
| semantic_scholar.py | YES | NO | MISSING |
| duckduckgo.py (3 sites) | YES | NO | MISSING |
| ollama.py (2 sites) | YES | NO | MISSING |
| openai_compat.py | YES | NO | MISSING |
| embeddings/base.py (4 sites) | YES | NO | MISSING |
| fetching.py (initial + per-hop) | YES | NO | MISSING |
| orchestrator.py (wiring) | N/A (construction) | NO | MISSING |

Result: **10/10 provider-level egress enforcement points lack a dedicated test.** The acceptance criterion "a test exists that verifies policy.require() blocks non-loopback under LOCAL_ONLY" is NOT met for any provider file.

## 5. Existing contract tests still pass (verified by running)

`pytest tests/invariants/test_search_failure_semantics.py -v` → **14 passed in 1.13s, exit 0** [RAN]. This confirms:

- `test_every_in_tree_provider_raises_on_a_transport_error` parametrizes duckduckgo, searxng, openalex, arxiv, crossref, semantic_scholar — all still raise `SearchProviderError` on transport errors with `policy=None` (backward compatibility preserved; INV-012 intact).
- The conftest `GAR_PLATFORM__SECURITY__LOCAL_ONLY=false` pin works (no ambient LOCAL_ONLY leakage blocking the offline suite).

These tests guard failure semantics, NOT egress policy. They pass with `policy=None` and therefore cannot detect a missing or reverted `require()` guard.

## 6. Mutation thinking — 5+ plausible egress-enforcement bugs and whether (committed) tests catch each

| # | Plausible bug (revert/mutate the fix) | Would committed tests catch it? | Notes |
|---|---|---|---|
| M-1 | Revert `router.py`: drop `policy` param / `ModelRouter.policy` / `build_provider(role_cfg, self.policy)` | NO — no router test exists; backward-compat `build_provider(cfg)` still works so `test_*` in test_search_failure_semantics.py unaffected | Regression detector: a test asserting `ModelRouter.for_role(role).policy` is set |
| M-2 | Remove `self.policy.require(...)` before `httpx.get` in openalex.py/crossref.py | NO — `test_every_in_tree_provider_raises_on_a_transport_error` uses `policy=None`, so the guard is skipped and the test passes either way | Regression detector: `OpenAlexProvider(policy=EgressPolicy("LOCAL_ONLY")).search()` → RuntimeError |
| M-3 | Same removal in arxiv.py / semantic_scholar.py | NO (same reason) | Regression detector: LOCAL_ONLY `search()` → RuntimeError before network |
| M-4 | Remove `require()` at one of the 3 duckduckgo httpx sites (e.g. the POST) | NO — no duckduckgo egress test; transport-error tests use policy=None | Regression detector: POST path under LOCAL_ONLY still reaches network |
| M-5 | Revert `fetching.py` to `follow_redirects=True` + single pre-flight check | NO — no fetching egress test; a 302 to an external host escapes validation | Regression detector: 302 chain localhost→external under LOCAL_ONLY → RuntimeError at second hop |
| M-6 | Drop `policy=policy` from one `build_default_registry` constructor call (orchestrator.py) | NO — no registry-forwards-policy test | Regression detector: provider built by registry lacks `.policy` under HYBRID/ONLINE |
| M-7 | `_host_of` returns `None`/empty instead of raising on unparseable URL (embeddings) | NO — no embedding egress test | Regression detector: unparseable base_url under LOCAL_ONLY must not reach network |
| M-8 | Widen `allows()` to True under LOCAL_ONLY (http_policy.py) — not a W2 file, but a mutation worth a test | Partially: construction-time empty-registry test (test_local_only_gating.py) would still pass (registry empty regardless), so NO for request-time | Regression detector: any provider request-time test under LOCAL_ONLY |

None of M-1..M-8 is detected by the existing committed suite. This is a genuine coverage gap: the fix is behaviorally correct but **unproven by tests**, so a revert would go undetected.

## 7. Missing edge cases — P1/P2/P3 prioritized list

**P1 (must have before wave close — acceptance criteria):**
1. Dedicated LOCAL_ONLY → `RuntimeError`-before-network test for each provider: openalex, crossref, arxiv, semantic_scholar, duckduckgo (GET+POST), searxng, ollama (chat+tags), openai_compat (chat), OllamaEmbeddingProvider/OpenAICompatibleEmbeddingProvider (embed+is_available), DocumentFetcher (initial URL + per-hop redirect).
2. `policy=None` backward-compat test for every constructor (existing callers unchanged) — partially covered by test_search_failure_semantics.py but should be explicit per provider.
3. `ModelRouter.for_role(role).policy == build_egress_policy(app_cfg)` and `build_provider(cfg, policy=pol)` forwards policy; `build_provider(cfg)` (policy=None) leaves `MockProvider` without a `policy` attr.
4. `fetching.py`: `follow_redirects=False`; 302-to-external refused under LOCAL_ONLY; per-hop re-validation (302 localhost→localhost→external caught at hop 2); `MAX_REDIRECTS=10` bound; constructor signature unchanged.
5. `build_default_registry` forwards `policy=policy` to all 6 constructors; `policy.strict` early-return (empty registry under LOCAL_ONLY) unchanged.

**P2 (important):**
6. HYBRID/ONLINE: `require()` passes (allows all hosts), network proceeds — verifies the policy isn't over-broad.
7. Malformed/None hostname → `is_loopback_host("")` → False → blocked under LOCAL_ONLY (fail-closed); `_host_of` raises on unparseable URL.
8. `RuntimeError` from `require()` is NOT swallowed by `except httpx.HTTPError` (duckduckgo/arxiv/semantic_scholar/ollama) — distinguishes policy block from transport failure.
9. Cross-project / config pin: conftest `GAR_PLATFORM__SECURITY__LOCAL_ONLY=false` keeps suite hermetic; a developer gar.yaml with local_only=true must not break offline tests (already pinned; test should assert the pin is respected or document why).

**P3 (defense in depth):**
10. Redirect loop exhaustion (`MAX_REDIRECTS`) returns `FetchedContent(status=0, error="too many redirects")`, no unbounded loop.
11. A 302 without `Location` header breaks the loop cleanly.
12. `LlamaCppProvider` inherits `_require`/`self.policy` enforcement for free (no separate change needed, but worth a smoke test).
13. `EgressPolicy.requires` / `allows` unit tests in isolation (host classification: loopback IPv4/IPv6/localhost True; everything else False under LOCAL_ONLY; True under HYBRID/ONLINE) — lives in `core/http_policy.py`, not owned by W2 but worth a dedicated test.

## 8. Reviewer's assessment of implementer verification quality

- All implementers did static import/signature checks and reasoned against `http_policy.py`/`config.py`; several ran inline (non-committed) `/tmp` verification scripts confirming RuntimeError-before-network behavior.
- W2-IMPL-06 and W2-IMPL-08 ran `tests/invariants/test_search_failure_semantics.py` (14 passed) as a regression check — correct scope.
- W2-IMPL-11 ran `tests/unit/ -k "fetch or fetcher or document"` → 2 passed — correct scope.
- W2-IMPL-05's scoped router `-k` collected 0 tests (no router tests exist) — correctly noted as a gap, not a pass.
- None ran the full suite, mutation_check, reaudit, or check_dist — correct per brief §7 / AGENTS §4.
- One concern: W2-IMPL-07's report references `tests/unit/test_stage1_dead_legs.py` matching `arxiv or semantic_scholar or academic` ("1 passed, 175 deselected") — that test does not exercise egress policy; it is a dead-legs test, not an egress regression detector. Correctly not treated as one.
- All implementers correctly respected write-set boundaries and posted NEED rather than creating test files. No FORBIDDEN-file violations in the source diff.

## 9. Out-of-scope findings (FINDING, not a blocker)

- `memory/retrieval.py` constructs `OllamaEmbeddingProvider`/`OpenAICompatibleEmbeddingProvider` directly without `policy` (W2-IMPL-10 §4.5) — those construction sites are not yet governed under LOCAL_ONLY. Flagged as DEFERRED-DEPENDENCY; requires a sibling change to pass `policy=build_egress_policy(cfg)`. Not a W2-REV-02 test-review blocker but worth tracking.
- `scripts/mutation_check.py` M-1..M-18 exist; none target egress policy or `core/ids.py` ULID (W5 M-19 was added by W1-IMPL-03 per COMMS). No mutation targets the new `require()` guards — a P2 candidate: add mutations that remove each `self.policy.require(...)` call and confirm detection.
- `docs/invariants.md` INV-029 and `docs/service-boundaries.md` were updated by W1-IMPL-02 (C19); no egress-policy invariant row exists yet for request-time enforcement. Consider adding one (docs, not source).

## 10. Verdict and required follow-up

**VERDICT: APPROVE-WITH-CHANGES.**

The source changes are correct, complete, minimal, and match all eight implementer reports. Existing contract tests still pass (14/14 verified). However, the acceptance criteria are **not satisfied** because no committed test verifies `policy.require()` blocks non-loopback under LOCAL_ONLY at any of the 10 enforcement points. Every W2 implementer posted a NEED for exactly this, and none could create test files (tests/ outside every write-set).

Required follow-up (outside W2-REV-02 write-set — post NEED to COMMS / assign to a test-owner agent):
1. Add dedicated egress enforcement test files under `tests/unit/` (one per provider group or a single `test_egress_enforcement.py`) covering P1 items 1–5.
2. Add mutation entries to `scripts/mutation_check.py` that remove each `self.policy.require(...)` call and confirm detection (P2/M-1..M-8).
3. Re-run `tests/invariants/test_search_failure_semantics.py` + any new egress tests + mutation_check after the tests land.

Report ends here. No source or test files were edited.
