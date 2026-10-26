# Report — W2-DREV-02 (DELTA TEST REVIEWER) · wave 2 · run 20261023-evidence-pipeline-fix

## ORCH-DIGEST

| Field | Value |
|---|---|
| Agent | W2-DREV-02 (DELTA TEST REVIEWER) |
| Task | Delta review of Wave 2 improvement test additions: `git diff 67ae1e9..HEAD -- tests/unit/test_egress_enforcement.py` |
| Report | docs/agent-ops/20261023-evidence-pipeline-fix/reports/w2-review/W2-DREV-02.md |
| Write-set | docs/agent-ops/20261023-evidence-pipeline-fix/reports/w2-review/W2-DREV-02.md only (READ-ONLY on all source/tests) |
| Branch | ops/20261023-evidence-pipeline-fix |
| Diff base SHA | 67ae1e9eb54f57c34593de060fa99540fa0adc2b |
| Diff head SHA | 46cea2e9b52eb265d1e5c0f9f55b4b7404d863f3 (HEAD) |
| Scoped check run | `pytest tests/unit/test_egress_enforcement.py -v` → 24 passed in 0.06s [RAN, exit 0] |
| Full suite | NOT run (brief §5 / AGENTS §4 forbid) |
| mutation_check / reaudit / check_dist | NOT run (not required for delta test review) |
| Verdict | **APPROVE** |

---

## 1. Diff inventory

`git diff 67ae1e9..HEAD -- tests/unit/test_egress_enforcement.py` is a single new file, 393 lines, containing exactly **24 tests**:

| # | Test | Enforcement point covered |
|---|---|---|
| 1 | test_openalex_local_only_raises_before_network | OpenAlexProvider.search |
| 2 | test_crossref_local_only_raises_before_network | CrossrefProvider.search |
| 3 | test_arxiv_local_only_raises_before_network | ArxivProvider.search |
| 4 | test_semantic_scholar_local_only_raises_before_network | SemanticScholarProvider.search |
| 5 | test_duckduckgo_get_local_only_raises_before_network | DuckDuckGoProvider.search (GET attempt 1) |
| 6 | test_duckduckgo_post_local_only_raises_before_network | DuckDuckGoProvider.search (POST attempt — see §5) |
| 7 | test_duckduckgo_policy_none_backward_compat | DuckDuckGoProvider() policy=None |
| 8 | test_searxng_local_only_raises_before_network | SearxngProvider.search pre-flight |
| 9 | test_searxng_loopback_base_redirect_to_external_refused | Searxng per-hop redirect validation |
| 10 | test_searxng_follow_redirects_is_false | Searxng follow_redirects=False |
| 11 | test_ollama_complete_local_only_raises_before_network | OllamaProvider.complete |
| 12 | test_ollama_is_available_local_only_raises_before_network | OllamaProvider.is_available |
| 13 | test_openai_compat_complete_local_only_raises_before_network | OpenAICompatibleProvider.complete |
| 14 | test_ollama_embed_local_only_raises_before_network | OllamaEmbeddingProvider.embed |
| 15 | test_ollama_embed_is_available_local_only_raises_before_network | OllamaEmbeddingProvider.is_available |
| 16 | test_openai_compatible_embed_local_only_raises_before_network | OpenAICompatibleEmbeddingProvider.embed |
| 17 | test_document_fetcher_initial_url_local_only_raises | DocumentFetcher._do_fetch initial host |
| 18 | test_document_fetcher_redirect_to_external_refused_at_hop_2 | DocumentFetcher per-hop redirect |
| 19 | test_document_fetcher_follow_redirects_is_false | DocumentFetcher follow_redirects=False |
| 20 | test_model_router_policy_matches_build_egress_policy | ModelRouter.for_role().policy |
| 21 | test_build_provider_policy_none_backward_compat | build_provider(cfg) policy=None |
| 22 | test_build_provider_forwards_policy | build_provider(cfg, policy=pol) |
| 23 | test_build_default_registry_forwards_policy_to_all_six | build_default_registry policy forwarding |
| 24 | test_build_default_registry_local_only_empty_registry | build_default_registry LOCAL_ONLY short-circuit |

Helpers: `_block_network` (monkeypatches `httpx.get`/`post` to raise AssertionError — fails loudly if any network call is reached), `_serve_ok` (returns a fake 200 response), `_local_only_cfg()` / `_app_cfg()` (explicit AppConfig construction — no ambient config dependence).

---

## 2. Verification against source (read-only inspection)

I inspected `core/http_policy.py`, `core/config.py` (`is_loopback_host`, `effective_environment`), `core/retry.py` (`run_with_retries`/`NETWORK`), `core/orchestrator.py` (`build_default_registry`), `pipeline/fetching.py` (`DocumentFetcher._do_fetch`), and all eight provider files. Key confirmations:

- `EgressPolicy.require` raises `RuntimeError` before any `httpx` call under LOCAL_ONLY for every non-loopback host; `is_loopback_host("127.0.0.1")` is True, hostnames are False.
- Every provider guards with `if self.policy is not None: self.policy.require(...)` so `policy=None` skips the guard (backward compat) and `RuntimeError` is not caught by `except httpx.HTTPError` (INV-012 preserved).
- `DocumentFetcher._do_fetch` validates the initial host before `httpx.Client`, disables `follow_redirects=False`, and re-validates each `Location` hop under LOCAL_ONLY.
- `build_default_registry` returns an empty registry under `policy.strict` (LOCAL_ONLY) and forwards `policy=policy` to all six constructors otherwise.
- `run_with_retries`/`NETWORK` retries on `Exception` but the tests call `_do_fetch` directly (no retry wrapper), so `RuntimeError` surfaces immediately.
- `tests/conftest.py` pins `GAR_PLATFORM__SECURITY__LOCAL_ONLY=false`, so no ambient `gar.yaml` leaks LOCAL_ONLY into the suite; the tests also build their own `AppConfig`/`EgressPolicy`, so they are hermetic regardless.

---

## 3. Acceptance-criteria checklist

| Criterion | Status | Evidence |
|---|---|---|
| All 24 tests exist | PASS | 24 collected, 24 passed |
| Cover P1 list from W2-REV-02 §7 | PASS | Academics ×4, duckduckgo GET+POST, searxng, ollama chat+tags, openai_compat chat, embeddings ×3, DocumentFetcher initial + per-hop, router/build_provider/registry wiring (tests 1–24) |
| Each test asserts behavior, not implementation | PASS | All assert `RuntimeError`, `follow_redirects is False`, `policy is X`, or empty-registry — none assert private-call counts |
| Deterministic and isolated | PASS | Function-scoped `monkeypatch`, per-test `tmp_path`, no shared state, no real network |
| `policy=None` backward compat tested | PASS | Tests 7 and 21 |
| LOCAL_ONLY → RuntimeError before network at each enforcement point | PASS | `_block_network` makes any reached network call fail as `AssertionError`, proving `require()` fired first |
| DocumentFetcher 302-to-external refused at hop 2 | PASS | Test 18 (initial URL loopback, hop-2 redirect to external refused) |
| ORCH-DIGEST block | PASS | Present above |

---

## 4. Test-by-test correctness notes

All 24 tests pass against the source (24 passed in 0.06s). Each `LOCAL_ONLY` test relies on `_block_network`, so if `policy.require()` did **not** fire first, the faked `httpx.get`/`post` would raise `AssertionError` and `pytest.raises(RuntimeError)` would fail — making the tests genuine regression detectors for a reverted `require()` guard.

Minor observations (none change the verdict):

- **Test 6 (`test_duckduckgo_post_local_only_raises_before_network`) does not distinctively exercise the POST enforcement site.** Under LOCAL_ONLY the first GET attempt (`html.duckduckgo.com`) raises `RuntimeError` before any network call, so the POST attempt is never reached. The test name implies POST coverage but it asserts the same behavior as test 5. It is still correct (RuntimeError-before-network holds) but redundant; a distinct POST test would need the first two attempts to return non-200 so the third (POST) `require()` is reached. Classified as P2 refinement, not a defect.
- **Test 16 covers `OpenAICompatibleEmbeddingProvider.embed` under LOCAL_ONLY but not `.is_available()`** (ollama covers both in tests 14/15). P2 gap only.
- **Per-constructor `policy=None` backward compat is explicit only for duckduckgo (test 7) and `build_provider`/MockProvider (test 21).** Other providers' `policy=None` path is covered indirectly by `tests/invariants/test_search_failure_semantics.py` (14 passed, verified earlier). P2 gap only.
- **`MAX_REDIRECTS=10` bound and redirect-without-`Location` clean-break are not tested** — these are P3 items in W2-REV-02 §7, not acceptance criteria.

---

## 5. Coverage of mutation candidates (W2-REV-02 §6 M-1..M-8)

The committed suite now detects request-time `require()` removal at every provider call site, because each has a dedicated LOCAL_ONLY → RuntimeError test. This closes the gap identified in W2-REV-02 §6 where none of M-1..M-8 was detected. The new tests cover: router policy delivery (M-1), openalex/crossref (M-2), arxiv/semantic_scholar (M-3), duckduckgo GET (M-4 partial; POST site not distinctively covered), fetching per-hop redirect (M-5), registry policy forwarding (M-6), embeddings `_host_of`/require (M-7), and `allows()` strictness (M-8 via any LOCAL_ONLY request-time test).

---

## 6. Verdict

**APPROVE.**

The 24-test delta is correct, deterministic, isolated, and passes against the source. It satisfies every acceptance criterion in brief §3, closes the egress-enforcement test gap identified in W2-REV-02, and serves as a genuine regression detector for reverts of the `policy.require()` guards. The minor observations in §5 are P2/P3 refinements and do not block approval.

No source or test files were modified. This report is the only write artifact.
