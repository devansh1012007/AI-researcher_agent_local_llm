# Plan: Evidence pipeline integrity, quality benchmark, analyst review

- Status: **IMPLEMENTED** | Tier: **L** (persistence, security, cross-module, schema)
- Repo state: branch `main`, commit `82d279c411ab66f1736304d1f562b3d2de1ca5ac`, date 2026-10-22
- Spec: operator message (2026-10-22) + `FIX_PLAN.md` (owner decisions D-1/D-2/D-3 already taken)
- Operator / agent: devansh / opencode (minimax-m3.1-flash)
- Baseline (measured): `308 passed, 1 skipped in 109.15s`; `run_eval.py --offline` -> gates PASS; `research doctor` -> degraded (llm/scheduler not running)
- Staleness rule: if `src/research_engine/{core,config.py,pipeline,platform,storage,reports,services}/`, `evals/`, or `docs/invariants.md` moves, re-verify section C/F before acting.

**Stages** (renamed from W1-W5 to avoid collision with `FIX_PLAN.md:824-838`'s W1-W10):

| Stage | Changes | Maps to FIX_PLAN wave |
|---|---|---|
| 1 - Dead legs, honest counts | C01-C06 | P1-13, P1-14 (+ new) |
| 2 - Collision-free ids | C07, C08, C22 | P0-3 (W5) |
| 3 - Enforced egress | C09-C12, C23 | P0-6 (W6) |
| 4 - Analyst review | C13-C16 | new |
| 5 - Quality benchmark | C17-C21, C24 | new (P3-1...P3-9 partial) |

## A. Problem, goal, success criteria

**Problem.** The product's headline claim is "evidence-first" (README:3-8). Three things hollow it: (1) retrieval legs that silently return nothing - `forum` (never resolvable) and `semantic_scholar` (routed on 3 branches, registered by default on none); (2) `platform.mode` is decorative - the API reports `LOCAL_ONLY` while the engine calls out [FACT `core/config.py:166-171` vs `core/orchestrator.py:649-671`]; (3) no measurement of research *quality* exists, so "is this good?" has no answer.

**Goal.** Honest evidence pipeline (no silent legs, enforced privacy, collision-free ids) + a human-labelled quality benchmark + an analyst sign-off path.

**Success criteria.** S1 zero route legs that resolve to no provider *and* are not explicitly marked optional. S2 the effective mode is enforced: under strict mode the process makes no outbound non-loopback socket. S3 no two entities share an id across processes; ids unique and monotonic within a process. S4 a human-labelled gold set exists; support-verdict precision/recall, contradiction-detection recall, and opportunity rank agreement are reproducible from one command with CIs. S5 an analyst can approve/reject a claim, annotate a contradiction, propose a validation-plan edit; every decision is persisted with reviewer label, timestamp, content hash, and appears in report provenance.

**Non-goals.** Merging `origin/agent/phase-7-production-learning`; web UI; multi-tenancy/auth/billing; replacing SQLite; LLM-as-evaluator; changing the claim-support algorithm; re-running analysis during report generation (INV-004); changing the *meaning* of the API's `environment` field.

**Constraints.** AGENTS.md binding. No CI - the agent is the gate. Hermeticity: the suite must not open sockets nor read the developer's `gar.yaml` [FACT `tests/conftest.py:12-31`].

**Reversibility.** Two-way for stages 1, 3, 5. Two-way for stage 2's code; **ids already written are never re-keyed** (re-keying breaks evidence->claim->source chains). Two-way for stage 4's code; new table is additive (orphan rows harmless).

## B. Glossary

**leg** - one provider route within a branch's search (PAIN = `["web","forum"]` = 2 legs). **leg outcome** - per-leg result: `hits` / `unconfigured` / `failed`. **grounding** - INV-005: quote EXISTS and claim SUPPORTED. **review decision** - a human's verdict on a claim/contradiction/validation plan, stored as its own row; never rewrites machine-owned state. **effective environment** - `LOCAL_ONLY` / `HYBRID` / `ONLINE`, resolved from config.

## C. Architecture of the affected code

- **Config** `core/config.py` - `AppConfig` is a plain BaseModel, no `extra="forbid"` => unknown YAML keys are silently ignored [FACT `:193-201`]; `respect_robots` `:55`; `local_only`/`privacy_mode` `:140-141`; `PlatformConfig.mode` default `"local"` `:158`; `effective_environment()` `:166-171`; `is_loopback_host()` fail-closed `:115-137`.
- **Provider construction** `core/orchestrator.py:649-671` `build_default_registry()` registers web + academic with **no environment check**; academic only if named in `cfg.search.academic_providers` (default `openalex,crossref,arxiv` [FACT `core/config.py:81-83`]) => `semantic_scholar` is routed but never registered.
- **Routing** `pipeline/routing.py:14-38` `DEFAULT_ROUTES`; `:79-86` `route_for()` blind-merges LLM `source_preferences` and strips `"forum"` specially; `:89-106` `ProviderRegistry` (private `_search`/`_academic`; public `get_search`, `get_any` - **no `academic` attribute**).
- **Retrieval** `pipeline/retrieval.py:65-95` `_cached_search` (cache key = provider+query; missing provider => `([], "")` = *not* a failure, pinned by [FACT `tests/invariants/test_search_failure_semantics.py:96-112`]); `:103-112` maps `documentation/government/company`->`"web"` but **not** `forum`, and appends each leg's hits to one flat list. The alias pair occurs in **4** routes (`CURRENT_STATE`, `BENCHMARKS`, `APPLICATIONS`, `REGULATIONS` - `routing.py:16-38`); `"company"` is aliased but appears in **no** route.
- **Watcher** `platform/watchers.py:143-177` - builds its own registry via `build_default_registry` (`:145-146`); constructs `DuckDuckGoProvider` directly (ignores `web_provider: none`); academic leg calls `reg.academic.get(name)` => `AttributeError`, swallowed by `except Exception: continue`; summary always `{"status":"OK"}` (`:132`); dead conditional `"SourceUpdated" if False else "EvidenceCreated"` (`:112-113`).
- **IDs** `core/ids.py:13-18` process-global counter; `seed_counter` has **zero callers** (`:21-23`); single funnel `models/base.py:27-30`; second caller `storage/graph_store.py:110-112`; upsert `ON CONFLICT(id) DO UPDATE` [FACT `storage/database.py:385-402`].
- **Ordering dependencies** `storage/graph_store.py:148,178` (`ORDER BY id`; graph rows have **no `created_at` column** [FACT `graph_store.py:73-97`], but the entity payload has `created_at: str` [FACT `:29`]) and `specialists/startup/data_repair.py:72-74` ("oldest duplicate wins").
- **Service seam** `services/knowledge_service.py:100-116` `trace_claim` reads `claim.evidence_ids` - **`Claim` has no such field** [FACT `models/evidence.py:67-82`; runtime: `AttributeError`]; `:287-296` `ExperimentService.approve` is the canonical human-approval precedent; `services/context.py:91-109` single global context, no tenancy.
- **Reports** `reports/generator.py` binds `claims = self.repos.claims.all(project.id)` at `:157, :177, :334, :410, :452`, then calls `build_findings_context(claims, evidence)` at `:191, :339, :413` and `deterministic_findings(claims, evidence)` at `:223, :420` [FACT `reports/synthesis.py:47, :64`]. `specialists/startup/reports.py` contains **zero** references to `claims` - it renders precomputed discovery/validation views.
- **Audit trail** `storage/events.py:16-44` per-project JSONL; `platform/events.py:41-59` `DomainEvent(type, project_id, job_id, payload, event_id, ts)` - **no actor field**; API auth is one shared `X-API-Token`, loopback unauthenticated by design (D-3) [FACT `api/app.py:429-458`].
- **Eval** `evals/metrics/eval_metrics.py:60` `score_project(repos, project_id, expected_subquestions)` - "All metrics are computed from persisted project state"; **has no access to report text**. Callers: `evals/runners/run_eval.py:204`, `tests/evaluation/test_eval_framework.py:24`, `test_phase2_acceptance.py:65`, `test_phase3_acceptance.py:152`. `evals/runners/run_eval.py:234-235` rewrites the tracked `evals/last_eval_results.json`. `evals/datasets/phase4_tasks.json:8-13` carries a `quality_gates` block the runner **never reads** (`run_eval.py:207` reads only `quality_expectations`).
- **Docs contracts** `docs/invariants.md` - 14 rows; the add-an-invariant protocol (`:23-27`) requires: one-sentence statement, **named enforcing module**, **unit + adversarial test** under `tests/invariants/`, and **a mutation** if it guards a formula. `docs/service-boundaries.md:21-24` is the canonical one-path-per-operation list.
- **Storage** `storage/database.py:12` `SCHEMA_VERSION = 1` - the stored meta value is only **read and compared** (`:354-358`), **never rewritten**, so bumping the constant is inert for existing DBs. `_EXTRA_TABLES` (`:178-308`) is executed with `CREATE TABLE IF NOT EXISTS` on every init (`:353`) => **a new table needs no migration**. `_migrate` (`:375-383`) only does `ALTER TABLE ... ADD COLUMN`. `_index_cols` is a **per-repository method** (`storage/repositories.py:35` base, `:99` `SearchQuery`; `storage/reasoning_repos.py:41`), not one function.

## D. Proposed design

**D.1 - One route map, explicit optionality.** `ROUTE_LEGS: dict[str, RouteLeg]` where `RouteLeg = (provider, query_suffix, optional)`. `query_suffix` gives the leg its own query text => distinct cache key => the `documentation/government` double-count disappears and `forum` becomes a real, differently-targeted search. `optional=True` marks a leg whose provider is only registered when the operator configures it (`semantic_scholar` needs `semantic_scholar_api_key` for reliable use). Every leg is then in exactly one of three states: **resolves** / **explicitly optional and unregistered** / **misconfigured** (a leg naming a provider that is not in the registry's vocabulary at all). S1 = zero legs in the third state. The `forum` special case in `route_for()` disappears; unknown LLM `source_preferences` are dropped against a closed leg-name set.

**D.2 - Two vocabularies, one contract.** *Input* (`platform.mode`): `offline | local | online`. *Resolved environment* (the API's `environment` field, unchanged): `LOCAL_ONLY | HYBRID | ONLINE`. Mapping: `offline->LOCAL_ONLY`, `local->HYBRID`, `online->ONLINE`; `privacy_mode: true` => `LOCAL_ONLY`; unknown mode => `LOCAL_ONLY` **and** a loud error + non-zero doctor exit (fail closed). `local` (default) = today's real behaviour (loopback LLM + network retrieval) with a truthful label; `offline` = zero non-loopback egress. The API response strings do **not** change - one breaking change (the config vocabulary), not two.

**D.3 - Egress enforced where the socket is.** One `EgressPolicy` (`core/http_policy.py`) exposing `allows(host) -> bool` built on the existing fail-closed `is_loopback_host`. It is consulted (a) at provider *construction* (no network provider is constructed in LOCAL_ONLY) and (b) at *every outbound request* - which, per verified grep, means touching all 12 direct call sites: `providers/academic/{openalex:25, crossref:24, arxiv:29, semantic_scholar:26}.py`, `providers/search/duckduckgo.py:55,58,104`, `providers/llm/{ollama:29,39, openai_compat:27}.py`, `providers/embeddings/base.py:77,87,106,116`, `pipeline/fetching.py:80`. These call module-level `httpx.get/post` with no shared client and no shared base (`providers/academic/base.py` is an ABC with no client), so enforcement means **routing them through one guarded client**, not adding a check to a helper that does not exist. `providers/llm/router.py:19 build_provider(cfg: LLMRoleConfig)` receives no `AppConfig` => its signature changes to accept the policy. `DocumentFetcher` follows redirects **manually** and validates each hop (a pre-flight check is defeated by a 302 to an external host). Under LOCAL_ONLY the global caches (`<data_dir>/_global/{search,fetch}_cache.sqlite`, built at `retrieval.py:29` / `fetching.py:54`) are neither read nor written (D-10).

**D.4 - The three measurements, split by what they actually need.**

| Measurement | Function | Model needed | Offline? |
|---|---|---|---|
| Support verdict precision/recall/F1 | `pipeline/claim_support.py:110-224` `verify_claim_support` - deterministic, model-free | **no** | **yes, hermetic** |
| Opportunity rank agreement | `specialists/startup/opportunities.py:155-266` `score_rubric` - deterministic given its inputs | **no** (inputs are fixture-pinned) | **yes, hermetic** |
| Contradiction **analysis** accuracy | `reasoning/contradiction_analyzer.py:40-107` - classifies an already-detected row | **no** | **yes, hermetic** |
| Contradiction **detection** recall/precision | `reasoning/contradiction_detector.py:49` - an LLM `structured` call | **yes** | **no - live tier, reported, never gated (D-8)** |

The gold set is **content-keyed**: every item's identity is `sha256` of its normalised content, never an entity id, so it survives the id change (T26). A contradiction-pair item is keyed by `sha256(sorted([norm(claim_a), norm(claim_b)]))`; `norm` = whitespace-collapsed, lowercased text. A support item is keyed by `sha256(norm(claim_text) + "\x00" + norm(quote))`.

**D.5 - Review is an overlay with a defined content hash.** `ReviewDecision` rows, appended, never updating machine state. `content_hash = sha256(norm(claim_text))` for claims (text only - deliberately id-free so it survives the id change), `sha256(norm(statement_a) + "\x00" + norm(statement_b))` for contradictions, `sha256(norm(assumption) + "\x00" + norm(cheapest_test))` for validation plans. A decision whose `content_hash` no longer matches the target is **stale**: surfaced, never auto-applied. "Latest wins" applies only among **non-stale** decisions; a stale decision never displaces a live one. Verdict vocabulary per target kind, with illegal transitions raising loudly (mirroring `reasoning/hypothesis_engine.py:32-50`).

**D.6 - Rejection is applied at the seam, read-only.** `reports/generator.py` binds `claims` at `:157, :177, :334, :410, :452` and passes the list to `build_findings_context` / `deterministic_findings`. The filter is applied to that **bound list** - a read of `review_decisions` and a filter of an in-memory list. No primary state is written during report generation => INV-004 holds (T23/T24). `specialists/startup/reports.py` needs **no** change (it never reads claims). The decision rows were written at decision time, not at render time.

**D.7 - Metric honesty, with a derivation rule.** `duplicate_rate` => true duplicate ratio, `rejection_rate` kept separate (the runtime metrics are already honest at `core/orchestrator.py:593-594`; only the eval scorer mis-wires it at `eval_metrics.py:75`). `dup_count` actually incremented (initialised and never incremented at `pipeline/evidence.py:216,250`, yet printed to users as "(duplicates: 0)" at `core/orchestrator.py:305`). `research_gain` formula fixed (it is zero offline only because `max_iterations=1` leaves no iteration *pairs* - the formula itself is sound). `citation_coverage` => **share of claims whose supporting evidence resolves to a non-rejected row whose quote re-verifies** - computed from persisted state, so `score_project` keeps its signature; the structurally-1.0 "claims with >=1 `supported_by`" is retired. **Threshold re-derivation rule** (D-7): thresholds are re-derived from the *new* metric's observed distribution on the *unchanged* golden tasks, and the derivation is recorded in the dataset file as `{"value": x, "derived_from": "<dataset+metric>", "rationale": "..."}` - the threshold may not be tightened to make a failing task pass; a task that fails after re-derivation is a **finding to fix**, not a threshold to move. The dead `quality_gates` block in `phase4_tasks.json:8-13` (never read by the runner) is either wired in or deleted - it is currently a promise with no implementation.

**D.8 - Benchmark shape.** One command: `python evals/runners/run_goldset.py [--live]`. Offline tier: hermetic, runs in pytest, writes a **new** file (`evals/gold/last_goldset_results.json`) - never the tracked `evals/last_eval_results.json`. Live tier: operator-invoked, needs a model, reports detection recall, **never gates**. Gate only at n>=300 labelled items; before that, report with CIs (D-7).

**D.9 - Identity.** `actor_kind in {os_user, unverified_label}` only. CLI decisions capture the OS user; API/MCP decisions (loopback is unauthenticated by design, D-3) are `unverified_label`. The trail proves *a decision was recorded*, not *who decided*, and no report may present it as accountability. No user/identity model (contradicts D-3, has no other consumer).

## E. Change list

| ID | File / symbol | WHAT | HOW | WHY not the alternative | Depends | Verified by | Risk | Revert |
|---|---|---|---|---|---|---|---|---|
| C01 | `services/knowledge_service.py:107` `trace_claim` | `claim.evidence_ids` -> `claim.supported_by`; also surface `contradicted_by` rows with a `role` key | read the two real fields; additive key | the headline chain crashes for every real claim (MCP `get_claim`/`trace_claim` => `-32603`) [FACT `mcp_server/server.py:332-333,405-414`]; CLI is fine because it uses `memory/qa.py:121-150` | - | T01, T30 | low | 1 line |
| C02 | `pipeline/routing.py` new `ROUTE_LEGS`; `pipeline/retrieval.py:103-112` | route->(provider, query_suffix, optional) map replaces the alias tuple; per-leg query text | static map; worker consumes it | the tuple (a) never mapped `forum`, (b) aliased `documentation/government/company`->`web` so **4** routes double-counted identical cached hits | - | T02, T03 | med | revert file |
| C03 | `pipeline/routing.py:14-38`; `core/orchestrator.py:649-671`; `core/config.py:81-83` | every leg's provider is in the registry vocabulary; `semantic_scholar` marked **optional** (registered only when the operator lists it in `academic_providers`); optional-and-unregistered is a first-class, visible state - never a silent zero | extend the map; make `route_for` report it | registering it by default adds an unauthenticated third-party call per run; deleting it removes a leg the routes already ask for | C02 | T02, T04 | low | revert |
| C04 | `pipeline/routing.py:79-86` `route_for`; `reasoning/novelty.py:35-38` | validate `source_preferences` against the closed leg set; drop unknown; delete the `"forum"` special case; `novelty` must report an unregistered provider explicitly instead of `continue` | membership check | an LLM-emitted name ("reddit", "semantic_scholar") currently becomes a silent empty leg; `novelty` is a **4th** silent leg | C02 | T04, T31 | low | revert |
| C05 | `platform/watchers.py:143-177` | `reg.get_any(name)`; web leg through the shared registry (honour `web_provider: none`); record `failed` vs `unconfigured`; fix the dead `if False`; **make the registry injectable** so the academic leg is testable; keep the watcher out of convergence | inject a `ProviderRegistry` instead of building one at `:145-146` | the academic leg has **never run** (`AttributeError` swallowed) and the web leg bypasses config, so an "offline" install still calls out | C02 | T05 | med | revert file |
| C06 | `models/research.py:44-61` `SearchQuery`; `pipeline/retrieval.py:45-46` | add `leg_outcomes`; `results_count` = distinct canonical URLs | one optional field in the `data` JSON column (no DDL) | `results_count` is a pre-dedup count inflated ~2x on 4 routes; per-leg visibility is the fix for the *class* | C02 | T06, T03 | med | revert field |
| C07 | `core/ids.py:13-23` | `next_id` -> monotonic ULID `<prefix>_<26-char Crockford base32>`; 48-bit ms + 80-bit random; monotonic within a millisecond; no new dependency; delete `seed_counter` (0 callers) | ~30 lines | D-1 chose prefixed ULID. The P0 is **collision**: two processes both mint `ev_000001` and the upsert **overwrites** the first row [FACT `storage/database.py:385-402`] | - | T07, T08, T09 | med | 1 function |
| C08 | `specialists/startup/data_repair.py:72-74`; `storage/graph_store.py:148,178` | order by `(created_at, id)` from the row payload instead of id text order | sort in Python over the same rows | **verified in SQLite**: BINARY order puts `ev_099999` *after* `ev_01M5G5CTDR...` (cross-over at legacy counter 100000) - the id-text assumption is false for mixed populations. `graph_store` has no `created_at` column, so it sorts on the payload field | C07 | T10, T32 | low | revert |
| C09 | **new** `core/http_policy.py`; `core/orchestrator.py:649-671`; `providers/llm/router.py:19`; `providers/academic/{openalex,crossref,arxiv,semantic_scholar}.py`; `providers/search/duckduckgo.py`; `providers/llm/{ollama,openai_compat}.py`; `providers/embeddings/base.py`; `memory/retrieval.py:151-170`; `pipeline/fetching.py:52-96`; `reasoning/novelty.py`; `experiments/runner.py:158`; `pipeline/retrieval.py:29,54` (cache paths) | one `EgressPolicy` (on `is_loopback_host`) consulted at construction **and** at all 12 direct `httpx` call sites - routed through one guarded client; `router.build_provider` gains the policy parameter; `DocumentFetcher` follows redirects manually and validates each hop; under LOCAL_ONLY the global caches are neither read nor written | new module + one guarded client + call-site edits | construction-time gating alone is bypassable: 4 academic providers and the search provider call module-level `httpx.get/post` with no shared client, and `fetching.py:80` uses `follow_redirects=True` (a 302 escapes a pre-flight check) [verified by grep] | - | T11, T12, T13, T33 | **high** | revert module + call sites |
| C10 | `core/config.py:139-171` `effective_environment`; `core/config.py:158`; `gar.example.yaml:63`; `.env.example:23` | input vocabulary `offline\|local\|online`; resolved environment unchanged (`LOCAL_ONLY\|HYBRID\|ONLINE`); unknown => `LOCAL_ONLY` + logged error; `privacy_mode` => `LOCAL_ONLY`; default `mode` stays `local` (= today's behaviour) | rewrite the resolver | keeping `local=>LOCAL_ONLY` with `local` as the default would make **the default install silently retrieve nothing** and still report success (an unconfigured provider is *not* a failure, so convergence sees no failure) | C09 | T14, T15 | **high** | revert resolver |
| C11 | `core/config.py:55`; `gar.example.yaml:39`; `docs/configuration.md` | delete `respect_robots`; retract the promise | delete knob + example line | D-2 says retract; the knob has **zero** read sites and `gar.example.yaml:39` promises robots.txt handling that does not exist. The operator's *untracked* `gar.yaml:39` keeps a dead key - harmless (`AppConfig` ignores unknown keys) but noted | - | T16 | low | revert |
| C12 | `api/app.py:461-499` `health_report`; `api/app.py:88`; `cli/main.py:1079-1091` `cmd_doctor`; `cli/main.py:1384` `main()` | doctor gains an **egress/providers** check: LOCAL_ONLY by configuration => "offline by configuration" (healthy); mismatch => "degraded" with reason; unknown mode => non-zero exit. `main()` must propagate a command's exit code (today `args.fn(args)`'s return is discarded - there is **no exit-code channel**) | add a `SystemExit`/return-code path | today doctor checks database/storage/llm/scheduler only - a no-network engine prints "healthy" [verified by running it] | C10 | T17, T34 | med | revert |
| C13 | **new** `models/review.py`; `models/__init__.py` `__all__`; `storage/database.py:178-308` `_EXTRA_TABLES`; **new** `storage/review_repos.py` (own `_index_cols`) | `ReviewDecision` (prefix `rev`): `target_kind`, `target_id`, `verdict`, `note`, `reviewer_label`, `actor_kind`, `decided_at`, `content_hash`; new table `review_decisions` in `_EXTRA_TABLES`; indexed cols declared in the DDL **and** in the new repo's `_index_cols` | new entity + repo | overlay table, not per-entity fields: machine status stays machine-owned (INV-005 `REJECTED` = "verification failed", not "human rejected"); per-project DB keeps INV-013 isolation. **No migration is needed** - `_EXTRA_TABLES` runs `CREATE TABLE IF NOT EXISTS` on every init (`database.py:353`) and `_migrate` only does `ADD COLUMN`; `SCHEMA_VERSION` is read-and-compared but **never rewritten** (`:354-358`), so bumping it is inert and is therefore NOT done (it would create false drift) | - | T18, T19 | med | drop table |
| C14 | **new** `services/review_service.py` | one authoritative path: `record_decision`, `list_decisions`, `apply_validation_plan_revision`; allowed verdicts per target kind (state machine mirroring `reasoning/hypothesis_engine.py:32-50`); illegal transition => loud error; latest-non-stale-wins; `content_hash` mismatch => stale, surfaced not applied | new service + repo | INV-008 forbids API/MCP touching storage; one operation = one path | C13 | T20 | med | revert |
| C15 | `cli/main.py`; `api/app.py`; `mcp_server/server.py` | `research review decide\|list\|revise`; `POST /projects/{id}/review/decisions`; MCP `record_review_decision` at permission tier **WRITE** (`security/permissions.py:13-30`) - all via `ReviewService` | thin adapters | same pattern as `ExperimentService.approve` [FACT `services/knowledge_service.py:287-296`] | C14 | T21, T22, T35 | low | revert adapters |
| C16 | `reports/generator.py:157,177,334,410,452` (claims binding) -> `:191,223,339,413,420`; `reports/synthesis.py:47,64` | filter rejected claims out of the bound `claims` list before `build_findings_context`/`deterministic_findings`; mark them in the output | filter the in-memory list; read `review_decisions` | filtering only in the renderer leaves the rejected claim in the synthesis prompt *and* in the deterministic fallback; `specialists/startup/reports.py` needs **no** change (zero claim references) | C14 | T23, T24 | med | revert filter |
| C17 | **new** `evals/gold/`; **new** `evals/metrics/label_metrics.py`; **new** `evals/runners/run_goldset.py` | content-keyed gold labels (support pair / contradiction pair / opportunity fixture); offline scorer: support precision/recall/F1, contradiction-**analysis** accuracy, opportunity rank correlation, Wilson/bootstrapped CIs; one command; separate output file | new files | the support verifier and the analyzer are **model-free** => measurable offline; the *detector* is not (D.4) | C07 | T25, T26, T36 | med | delete files |
| C18 | `evals/metrics/eval_metrics.py:75,91-93,118-131`; `pipeline/evidence.py:216,250`; `core/orchestrator.py:305`; `evals/datasets/*.json`; `scripts/mutation_check.py` | `duplicate_rate` => true duplicate ratio (`rejection_rate` separate); `citation_coverage` => share of claims whose support resolves to a non-rejected row whose quote re-verifies; `research_gain` formula; `dup_count` incremented; re-derive tracked thresholds **by the recorded rule** (D.7); wire in or delete the dead `phase4_tasks.json:8-13` `quality_gates` block | redefine + **mutation first** | the current metrics are tautological or misnamed; a benchmark on them measures nothing (BD-06). `score_project` keeps its signature - the new `citation_coverage` is computable from persisted state | - | T27, T28, M-16...M-19 | high | revert + re-derive |
| C19 | `docs/invariants.md`; `docs/service-boundaries.md:21-24`; `tests/invariants/test_system_invariants.py:60-63` `TABLES` | add rows **INV-026...INV-029** (not 015-025 - that whole range is taken by the unmerged phase-7 branch, which also renames INV-014): no silent legs, enforced environment, collision-free ids, review decisions are append-only and never rewrite machine state. Each names its enforcing module, an **adversarial** test, and (for INV-026/027) a mutation. Add `review_decisions` to the INV-004 purity `TABLES` list. Add the review operation to the canonical one-path list | new rows + doc + list edits | the repo's own protocol (`docs/invariants.md:23-27`) requires unit **+ adversarial** test and a mutation for formula guards - a row alone is not compliance | C02,C07,C10,C13 | T29, T37 | low | revert rows |
| C20 | `FIX_PLAN.md`; `docs/development.md`; `README.md` | update the wave table with the old->new stage mapping; fix stale counts (README says "80 tests"; actual 308) | doc edits | docs must describe the final state (AGENTS 15) | all | - | low | revert |
| C21 | `evals/runners/run_eval.py:207`; `evals/datasets/phase4_tasks.json:8-13` | wire the `quality_gates` block into the runner **or** delete it, and say which | one or the other | it is a promise with no implementation; leaving it is the "unused config" anti-pattern | C18 | T38 | low | revert |
| C22 | `specialists/startup/data_repair.py`; `storage/graph_store.py` (graph payload) | confirm ULID id ordering is used only for *display*; if any consumer depends on creation order, switch it to the payload `created_at` | audit + fix | with ULIDs the order still approximates time order, but the plan flags the dependency and must not leave it unowned | C07, C08 | T32 | low | revert |
| C23 | `core/orchestrator.py:649-671`; `providers/llm/router.py`; `core/config.py` | make the **effective environment** reachable where the registry is built, so `build_default_registry` and `build_provider` cannot disagree about it | pass one resolved value | two independent reads of `effective_environment()` are how the current lie arose | C09, C10 | T11, T14 | med | revert |
| C24 | `evals/metrics/eval_metrics.py:60`; `evals/runners/run_eval.py:204`; `tests/evaluation/test_eval_framework.py:24`; `test_phase2_acceptance.py:65`; `test_phase3_acceptance.py:152`; `tests/invariants/test_interface_contracts.py` | if any metric signature changes, update **every** caller listed here, and add a conformance assertion for the new MCP tool + the changed `trace_claim` payload shape | enumerate | `score_project` has 5 call sites; a changed payload shape is machine-readable and pinned by the interface-contract test | C01, C17, C18 | T30, T35 | med | revert |

**Ordering rationale.** Stage 1 first: cheapest, no schema change, and it makes the dead-leg class *visible* - which stage 5 then measures. Stage 2 second: removes the P0 that silently destroys rows, and must precede stage 5 so gold labels are content-keyed from the start. Stage 3 third: highest blast radius, and it benefits from a pipeline that is already honest. Stage 4 fourth: review decisions become the *source* of human labels for stage 5. Stage 5 last: it measures the pipeline as it finally is.

**Deviation from `FIX_PLAN.md:838-843`** (which schedules ULID late, "after waves that add entities and rows"). [OPINION] The note's cost - re-verifying those waves' tests against two id formats - is near zero *here* because no test asserts an id format [verified: the only id assertion is "3 distinct ids" in `tests/unit/test_evidence_validation.py:23-26`], the gold set is content-keyed, and the two id-ordering consumers get an explicit `created_at` fix (C08, C22). The upside is closing a silent-row-destruction P0 two stages sooner. [ASSUMPTION] "no per-project DBs exist in this checkout" is true but irrelevant - they are created at runtime; the argument above does not rest on it.

## F. Files affected

| File | Change | IDs | Why | Also depends on |
|---|---|---|---|---|
| `pipeline/routing.py` | modify | C02,C03,C04 | route map is the source of the dead-leg class | retrieval worker, orchestrator |
| `pipeline/retrieval.py` | modify | C02,C06,C09 | leg execution, outcomes, cache paths | routing, models, http_policy |
| `models/research.py` | modify | C06 | `leg_outcomes` field | database |
| `platform/watchers.py` | modify | C05 | dead academic leg + direct provider construction | routing, orchestrator |
| `core/ids.py` | modify | C07 | id generation | models, graph_store |
| `specialists/startup/data_repair.py` | modify | C08,C22 | oldest-wins ordering | ids |
| `storage/graph_store.py` | modify | C08,C22 | id-text ordering | ids |
| `core/config.py` | modify | C09,C10,C11 | modes, privacy, robots retraction | orchestrator, providers, doctor |
| `core/orchestrator.py` | modify | C03,C09,C18,C23 | registry gating, duplicate metric | config, retrieval |
| `core/http_policy.py` | new | C09 | single egress policy | providers, fetching |
| `providers/academic/{openalex,crossref,arxiv,semantic_scholar}.py` | modify | C09 | direct httpx calls | http_policy |
| `providers/search/duckduckgo.py` | modify | C09 | direct httpx calls | http_policy |
| `providers/llm/{ollama,openai_compat,router}.py` | modify | C09,C23 | direct httpx calls; policy param | http_policy |
| `providers/embeddings/base.py` | modify | C09 | direct httpx calls | http_policy |
| `pipeline/fetching.py` | modify | C09 | manual redirect following; cache path | http_policy |
| `memory/retrieval.py`, `reasoning/novelty.py`, `experiments/runner.py` | modify | C04,C09 | remaining egress paths | http_policy |
| `models/review.py` | new | C13 | review decision entity | - |
| `models/__init__.py` | modify | C13 | export the new entity | models/review.py |
| `storage/database.py` | modify | C13,C19 | review table DDL | - |
| `storage/review_repos.py` | new | C13 | review repo + `_index_cols` | database |
| `services/review_service.py` | new | C14 | canonical path | repos |
| `services/knowledge_service.py` | modify | C01 | trace fix | review_service |
| `cli/main.py`, `api/app.py`, `mcp_server/server.py` | modify | C12,C15 | review + doctor surfaces | review_service |
| `reports/generator.py`, `reports/synthesis.py` | modify | C16 | excluded-claim rendering | review_service |
| `evals/metrics/eval_metrics.py` | modify | C18,C24 | honest metrics | - |
| `evals/metrics/label_metrics.py` | new | C17 | gold scorer | claim_support, contradiction_analyzer |
| `evals/runners/run_goldset.py` | new | C17 | gold runner | label_metrics |
| `evals/gold/` | new | C17 | labelled fixtures | - |
| `evals/runners/run_eval.py`, `evals/datasets/*.json` | modify | C18,C21,C24 | threshold re-derivation; dead gate block | eval_metrics |
| `scripts/mutation_check.py` | modify | C18 | new mutations for new scorers | - |
| `docs/invariants.md`, `docs/service-boundaries.md`, `docs/development.md`, `README.md`, `FIX_PLAN.md` | modify | C19,C20 | contract + drift | - |
| `gar.example.yaml`, `.env.example` | modify | C10,C11 | mode vocabulary; robots retraction | config |
| `tests/**` | new/modify | T01-T38 | proof | all |

## G. Alternatives and decisions

| ID | Decision | Options considered | Chosen | Why chosen | Why others rejected | What would change our mind |
|---|---|---|---|---|---|---|
| D-1 | Privacy mode vocabulary | (a) `offline\|local\|online`, `local`=today's behaviour, `offline`=strict; (b) keep `local`=LOCAL_ONLY strict, flip the default; (c) implement `privacy_mode` only | (a) | makes every documented promise true, the default install keeps working, strict mode is opt-in and actually strict | (b) silently darkens every existing `mode: local` install (incl. the operator's untracked `gar.yaml:63`) and flips the default's meaning; (c) leaves `mode` decorative | wanting `mode: local` to be strict today, accepting a documented breaking change |
| D-2 | ULID wave placement | (a) early (stage 2); (b) last, per `FIX_PLAN.md:838-843` | (a) + the C08/C22 ordering fix | closes a silent-destruction P0 now; no test asserts an id format; the gold set is content-keyed | (b) leaves the P0 open for the whole plan | wanting strict adherence to the documented wave order |
| D-3 | Route-leg fixes | (a) explicit route map + per-leg outcomes; (b) patch only `forum`; (c) treat missing provider as a failure | (a) | fixes the class; (b) leaves `semantic_scholar` and the double-count; (c) breaks the pinned invariant "unconfigured != failure" | (c) makes offline installs report degraded | accepting a change to `test_search_failure_semantics.py` |
| D-4 | Review data model | (a) append-only overlay table; (b) per-entity status fields; (c) reuse `EvidenceStatus.REJECTED` | (a) | keeps machine state machine-owned; full history; one query | (b) multiplies schema churn across 4 entity types; (c) conflates "verification failed" with "human rejected" | wanting review state queryable without a join |
| D-5 | Review identity | (a) free-text label + `actor_kind`; (b) OS user only; (c) real identity model | (a) with OS-user default | D-3 makes loopback unauthenticated => no identity can be *trusted*; (c) contradicts D-3 with no other consumer | (b) is a local-machine fact, not a person | introducing real auth (out of scope here) |
| D-6 | Review blast radius | (a) exclude from synthesis, mark elsewhere; (b) exclude everywhere + re-score; (c) record only | (a) | excluded from the synthesis prompt and the deterministic fallback, without re-running analysis (INV-004) | (b) re-runs analysis and changes every reported number; (c) leaves the sign-off decorative | wanting rejected claims to re-score |
| D-7 | Gold set standard | (a) report at n=100, gate at n>=300; (b) report only; (c) gate at n=100 | (a) | n=100 => ~+/-10pp, n=300 => ~+/-5pp; a 50-item set supports no threshold at all | (b) no protection against regression; (c) the threshold is noisier than it looks | accepting a noisier gate |
| D-8 | Label provenance + live tier | (a) human labels, live tier reported not gated; (b) human labels + live model here; (c) model-assisted labels | (a) | D23: offline fakes mask the claim-faithfulness hole; no model is reachable on the build host | (b) impossible here (`:11434`, `:8080`, `:8000` refused); (c) biases the benchmark toward the model's blind spots | provisioning a stable hosted model |
| D-9 | Plan file location | `docs/plans/2026-10-22-evidence-pipeline-and-analyst-review.md` | chosen | docs/ is flat (40 files, no subdirs); a plans/ subdir keeps living documents out of the subsystem-doc set | - | preferring a flat file in docs/ |
| D-10 | Strict mode + global cache | (a) disable read/write under strict mode; (b) environment-scope the cache path | (a) | simpler, and cannot leak network-derived documents into a run that promised no external data | (b) preserves provenance but adds a second cache namespace; the red-team review preferred it | wanting cached evidence reusable in strict mode |
| D-11 | `results_count` semantics | (a) distinct canonical URLs; `sources_accepted/rejected` unchanged; (b) both change; (c) neither changes | (a) | matches what a reader sees; the source counters count rows, not hits | (b) changes a second, unrelated metric; (c) leaves the ~2x inflation | - |
| D-12 | `semantic_scholar` | (a) optional leg; (b) register by default; (c) remove from the 3 routes | (a) - **stated default, flag for the operator** | avoids adding an unauthenticated third-party call per run, and keeps the routes' intent visible rather than deleting it | (b) adds per-run network cost and rate-limit exposure; (c) silently drops a leg the planner asks for | wanting full academic coverage out of the box |
| D-13 | Threshold re-derivation | the recorded rule in D.7 | chosen | a threshold fitted to make a failing task pass is the anti-pattern this plan attacks | - | - |

## H. Tests and validation

**Existing guarantees:** 308 pass / 1 skipped (measured). `docs/invariants.md` lists **14** invariant rows, enforced by **70** test functions under `tests/invariants/`. `scripts/mutation_check.py` M-1...M-15 detected; `scripts/reaudit.py` 14/14.
**Existing gaps:** no test reads `platform.mode`; none asserts id format; none touches `DEFAULT_ROUTES`; the only watcher-search test monkeypatches `_search` wholesale; no test asserts a research-quality property.

| ID | Level | Scenario | Expected | Proves | New? |
|---|---|---|---|---|---|
| T01 | integration | `trace_claim` on a **real** claim (MCP `get_claim` + `trace_claim`) | chain returned, no `AttributeError`, contradicting evidence present with `role` | C01 | new |
| T02 | unit | **default** `AppConfig()` (not the `cfg` fixture, which clears `academic_providers` and pins `web_provider=none`) => every leg resolves or is explicitly optional; zero misconfigured legs | S1, C03 | new |
| T03 | unit | branch with two legs on one provider => `results_count` == distinct canonical URLs == distinct results | C02, C06 | new |
| T04 | unit | LLM emits an unknown `source_preferences` entry | dropped, route intact, no empty leg | C04 | new |
| T05 | integration | watcher with an **injected** registry: `web_provider: none` => no outbound call; a failing provider => summary says failed, not OK; the academic leg runs and returns hits | C05 | new |
| T06 | integration | query row after a mixed-leg run | `leg_outcomes` present, per-leg status (`hits`/`unconfigured`/`failed`) | C06 | new |
| T07 | unit | 10 000 ids in one millisecond | strictly increasing, unique, matches `<prefix>_[0-9A-HJKMNP-TV-Z]{26}` | C07 | new |
| T08 | integration | **two processes** => one project DB | disjoint id sets; row count grows by 2 | S3, C07 | new |
| T09 | unit | legacy `ev_000042` and a new ULID coexist | both readable; no overwrite | C07 | new |
| T10 | unit | `data_repair` on a duplicate group containing a legacy high-counter id | keeps the genuinely oldest member | C08 | new |
| T11 | unit | LOCAL_ONLY + **each** provider constructor, incl. `router.build_provider` | no network provider constructed; non-loopback URL refused at the client | S2, C09, C23 | new |
| T12 | integration | LOCAL_ONLY, full research run, **socket probe** with the *real* provider classes and a stub transport - NOT the mock-pinned suite config (which passes vacuously) | zero outbound non-loopback connections | S2 | new |
| T13 | unit | `DocumentFetcher` against a transport returning 302 to an external host | redirect refused at the hop | C09 | new |
| T14 | unit | `platform.mode` unknown; `privacy_mode: true` | resolved environment `LOCAL_ONLY`; error logged; doctor exit non-zero | C10, C23 | new |
| T15 | unit | `mode: local` (default), **default `AppConfig()`** | retrieval providers registered; behaviour identical to today | C10 | new |
| T16 | unit | `respect_robots` | absent from `AppConfig` and `gar.example.yaml` | C11 | new |
| T17 | unit | doctor under LOCAL_ONLY | reports "offline by configuration", not "healthy-but-broken" | C12 | new |
| T18 | unit | review decision persisted | row carries verdict, reviewer label, actor kind, timestamp, content hash, target | C13 | new |
| T19 | unit | two decisions on one target; one made stale by a text edit | latest **non-stale** wins; stale surfaced, not applied | C13, C14 | new |
| T20 | unit | illegal verdict transition | loud error | C14 | new |
| T21 | integration | CLI + API + MCP decide | all three reach `ReviewService`; one path | C15, INV-008 | new |
| T22 | scan | API/MCP/CLI | no direct storage construction (extends `TestServiceBoundaries`) | C15 | modify |
| T23 | unit | rejected claim + report generation | claim absent from `findings_input` **and** the deterministic fallback; zero writes to primary state (INV-004) | C16 | new |
| T24 | unit | report generation with `review_decisions` present in the purity `TABLES` list | row count unchanged across generation | C16, C19 | modify |
| T25 | unit | gold scorer on a labelled fixture with a known confusion matrix | precision/recall match the fixture; CI reported | S4, C17 | new |
| T26 | unit | gold labels are content-keyed | identical results after an id-format change | C17 | new |
| T27 | unit | `duplicate_rate` vs `rejection_rate` | distinct quantities, distinct names | C18 | modify |
| T28 | unit | `dup_count` after a duplicate claim | non-zero; orchestrator log line truthful | C18 | new |
| T29 | invariant | each new invariant row | its named enforcement + its adversarial case exercised | C19 | new |
| T30 | contract | `trace_claim` payload shape | the new `role` key is asserted; MCP contract test updated | C01, C24 | modify |
| T31 | unit | `novelty` with an unregistered provider | reports "unconfigured" explicitly, not a silent skip | C04 | new |
| T32 | unit | `graph_store` ordering after the id change | ordering is by payload `created_at`; oldest-first still holds | C08, C22 | new |
| T33 | unit | egress policy at **every** direct `httpx` call site (9 provider modules) | each raises/refuses under LOCAL_ONLY | C09 | new |
| T34 | contract | `research doctor` exit code | non-zero on unknown mode / mismatch | C12 | new |
| T35 | contract | new MCP tool present in the interface-contract test's `schema_args` | invoked with valid args; unknown-arg path fails cleanly | C15, C24 | modify |
| T36 | unit | gold set pair key | the same pair hashes identically regardless of id format or ordering of the two claims | C17 | new |
| T37 | invariant | the 4 new invariant rows carry an **adversarial** test and, where formula-guarding, a mutation | each present and detected | C19 | new |
| T38 | unit | `phase4_tasks.json` `quality_gates` | either read by the runner or absent from the file | C21 | new |
| M-16...M-19 | mutation | mutate the new/changed scorers (`duplicate_rate`, `citation_coverage`, `dup_count`, `research_gain`) | each mutation DETECTED | C18 | modify |

**Baseline:** `pytest` (308 passed / 1 skipped / ~109 s, offline) - `pytest tests/invariants` - `python scripts/mutation_check.py` (15/15 + M-16...M-19) - `python scripts/reaudit.py` (14/14).
**Non-test validation:** `research doctor` under each of the three modes; one strict-mode research run with a socket probe; one live run with a real model to produce the first detection-recall figure (operator-invoked - no model is reachable on this host: `localhost:11434`, `:8080`, `:8000` all refused [verified]).

## I. Edge cases (derived from this code)

`mode: local` is the **default** (`config.py:158`) => must not mean "no retrieval" (C10, T15). Legacy ids >= 100000 sort after ULIDs (verified in SQLite) => oldest-wins by `created_at` (C08, T10). `Entity` is `extra="forbid"` (`models/base.py:14`) => a row with `leg_outcomes` breaks an older engine => the field is optional and the DB is versioned by content, not by engine (C06). The global caches hold network-derived data (`AGENTS.md` landmine) => not read/written under LOCAL_ONLY (C09; T11/T12/T33). A 302 to an external host escapes a pre-flight check (`fetching.py:80`) => redirects followed manually and validated per hop (C09, T13). Two legs on one provider share a cache key => distinct `query_suffix` per leg (C02, T03). A reviewer posts from an unauthenticated loopback API (D-3) => `actor_kind=unverified_label`; the trail proves a decision was *recorded*, not *who decided* (C13, C14). A claim edited after a decision => decision stale, not applied (C14, T19). `evals/last_eval_results.json` is tracked and rewritten by the runner => the new runner writes elsewhere (C17). `citation_coverage` redefinition invalidates tracked thresholds => re-derived by the recorded rule, not to make a failing task pass (C18, D.7). `dup_count` printed to users (`core/orchestrator.py:305`) => a real number (C18, T28). `_index_cols` is per-repository, not one function => the new repo owns its own (C13). `SCHEMA_VERSION` is read-and-compared but never rewritten => a bump is inert and is not done (C13). `phase4_tasks.json`'s `quality_gates` is never read => wired or deleted (C21).

## J. Impact, second-order effects, compatibility

**Blast radius:** retrieval (every branch), watcher jobs, provider construction, all four HTTP provider families, document fetching, embeddings, the config surface, doctor, the report layer, the eval framework, and the MCP/API/CLI surface.
**Compatibility:** `platform.mode` values change meaning => **documented breaking change** (D-1, D-2) - the *API* `environment` strings do not change. `respect_robots` removed - harmless for existing `gar.yaml` (`AppConfig` ignores unknown keys, `config.py:193-201`), but the operator's untracked `gar.yaml:39` keeps a dead key. `evals/datasets/*.json` thresholds re-derived by the recorded rule.
**Concurrency:** review decisions are append-only rows; no state machine on primary entities => no writer conflict. ULID monotonicity is per-process; cross-process order within a millisecond is not creation order (accepted; the two ordering consumers get the C08/C22 fix).
**Performance:** a small JSON field per query row; a dict lookup per leg; one host check per request.
**Security:** the strict mode closes a real gap. Loopback stays unauthenticated (D-3), so the review overlay is **not** accountability evidence and must never be presented as human sign-off.
**Second-order effects:** once `environment` is truthful, users may *rely* on it - "why is my research empty" reports will surface. Once legs are visible, branch-coverage numbers change. Once the gold set exists it becomes an asset that must be protected from over-fitting (train/val/test split, D-8).

## K. Rollout, rollback, observability

**Order:** stage 1 -> 2 -> 3 -> 4 -> 5, each an independent commit series with its own review subagent (AGENTS 2.3), each re-running the full suite + `mutation_check` + `reaudit`.
**Flags:** none new; config switches only (`platform.mode` vocabulary, `privacy_mode`).
**Point of no return:** none for stages 1, 3, 5 (revert restores behaviour); stage 2's ULID ids are never re-keyed; stage 4's table is additive (orphan rows harmless).
**Rollback:** each stage is a self-contained `git revert` + re-run the suite; a mis-shipped stage 3 is neutralised by setting `platform.mode: local`.
**Observability:** doctor gains the egress/providers check (C12); per-leg outcomes on the query row (C06); the watcher summary carries failures (C05); the gold runner prints precision/recall + CIs (C17); `research trace-claim` works again (C01) - itself the first visible proof the traceability chain is alive.

## L. Risks, assumptions, open questions

| ID | Type | Description | L x I | Mitigation or how to verify | Owner | Status |
|---|---|---|---|---|---|---|
| R-01 | risk | stage 3 breaks the default install | M x H | C10 keeps `local` = today's behaviour; T15 pins it; C12 surfaces mismatch | - | by design |
| R-02 | risk | egress policy bypassed by an unenumerated path | M x H | T33 enumerates all 9 provider modules; T12 socket probe over a real-provider run | - | open until T12/T33 pass |
| R-03 | risk | gold set too small to gate on | H x H | n=100 => ~+/-10pp, n=300 => ~+/-5pp; a 50-item set supports no threshold => report only until n>=300 (D-7) | - | accepted |
| R-04 | assumption | a real model is reachable for the live tier | H x H | **not reachable on this host** => the live tier is operator-invoked and reported, never gated (D-8) | operator | accepted |
| R-05 | assumption | gold labels are human-authored | M x H | D23: offline fakes mask the claim-faithfulness hole; the labelling pass is the schedule risk | operator | open - operator's labelling time |
| R-06 | risk | `citation_coverage` redefinition breaks tracked thresholds | M x M | re-derive by the recorded rule; mutation-first; a failing task is a finding, not a threshold to move | - | mitigated |
| R-07 | risk | the review overlay becomes a second source of truth | M x M | overlay only; machine state untouched; filter at the seam; INV-023 | - | by design |
| R-08 | risk | ULID embeds wall-clock time; clock-skew sensitive | L x L | accept and document; ids are not secrets | - | accepted |
| R-09 | risk | phase-7 reused by accident (it renames INV-014 and takes INV-015...025) | L x M | explicit non-goal; the new rows use **INV-026...029**; its review path is non-functional | - | closed |
| R-10 | risk | "do nothing for a month" | H x H | the evidence-first claim stays unfalsifiable; the monetization story rests on it | operator | - |

**Pre-mortem - the change shipped and failed badly.** (1) *default install silently retrieves nothing* - early signal: doctor says healthy while a run returns 0 sources - mitigation C10/T15/C12. (2) *egress bypass* - early signal: T12 shows one unexpected socket - mitigation R-02. (3) *gold set too small to gate on* - early signal: CI band wider than any effect - mitigation R-03. (4) *labels are model-generated* - early signal: label distribution matches the model's own bias - mitigation R-05. (5) *rejection breaks report grounding* - early signal: report cites fewer claims than the evidence table - mitigation T23/T24.

## M. Decision log and discussion changelog

- **D-1...D-11** - operator-confirmed 2026-10-22 (see section G).
- **D-12, D-13** - stated defaults, flagged for the operator.
- **Rejected:** merging `origin/agent/phase-7-production-learning` (renames INV-014, takes INV-015...025, its review path calls `platform_db.save_review` which that branch never defines => non-functional) - borrow the design, not the code. A user/identity model (contradicts D-3). Re-running analysis during report generation (violates INV-004/BD-02). LLM-as-judge (D23). Making a missing provider a failure (breaks a pinned invariant). Environment-scoping the global cache (D-10's simpler disabling). A real `SCHEMA_VERSION` bump (inert - never rewritten).
- **Changelog:**
  - r1 - initial plan.
  - r2 - red-team findings folded in: the `claim.evidence_ids` crash is a *live* crash, not merely wrong; the `semantic_scholar` x3 dead legs; the `documentation/government` double-count; the ULID ordering crossover at legacy counter 100000 (verified in SQLite); the `mode: local` default-install blocker; the redirect bypass; phase-7's review path being non-functional; corrected the mis-claimed `new_information_rate`/`research_gain` behaviours.
  - r3 - operator decisions D-1...D-11 folded in.
  - r4 - cold-read pass: 12 defects fixed - the offline/live metric split (C17/D.4); the 12 direct `httpx` call sites and the `router.build_provider` signature (C09); the `score_project` signature and its 5 callers (C18, C24); the threshold re-derivation rule and the dead `quality_gates` block (C18, C21); the conftest-pinned-suite trap in T02/T12/T15; the missing doctor exit-code channel (C12); the wave-naming collision and the W-mapping error; the "new table needs no migration / SCHEMA_VERSION is inert" storage correction (C13); the undefined `content_hash` (D.5) and gold pair key (D.4); the full invariant protocol (adversarial + mutation) (C19); the C16 change points and the unnecessary `specialists/startup/reports.py` edit; the vacuous T12; the T13 fake-transport gap; the injectable-registry requirement (C05); the effective-environment output vocabulary (D.2); the INV-015...025 collision (INV-026...029); the `docs/service-boundaries.md` update (C19).
  - r5 - approved by the operator 2026-10-22; implementation begins.
  - r6 - stages 1-5 implemented (C01-C24): dead legs fixed, honest counts,
    ULID ids, enforced egress (http_policy + mode vocabulary), analyst review
    overlay (ReviewDecision + ReviewService + CLI/API/MCP + report filtering),
    quality benchmark (gold fixtures, label_metrics, run_goldset), honest
    metrics (citation_coverage re-verifies quotes, dup_count incremented),
    quality_gates wired into run_eval.py. All gates green: 378 passed / 1
    skipped, 18/18 mutations detected, reaudit 14/14. Stale test counts fixed
    in README/docs/development.md; INV-026 added; INV-015..025 reserved for
    phase-7 branch.

## N. Approval record

- **Readiness checklist:** PASS - every blocking question answered (D-1...D-11) - success criteria observable with a test mapped to each (S1->T02, S2->T11/T12/T33, S3->T07/T08, S4->T25, S5->T18/T21/T23) - every change entry has file, symbol, what, how, why-not-alternative, dependency, test, revert - every file in section F appears in section E and vice versa - before/after flows reference verified symbols - alternatives compared incl. "do less" and "reuse existing X" - edge cases drawn from this codebase - tests cover sections I and L, not just the happy path - rollback and observability stated - assumptions have an early, cheap verification step - the cold-read agent answered all six questions and its defects are folded in.
- **Accepted risks (explicit):** R-03 (no gate before n=300) - R-04 (live tier needs an operator-supplied model) - R-05 (labelling effort is on the operator) - R-08 (ULID time embedding) - D-12 (semantic_scholar stays optional by default).
- **Operator approval:** "write the plan and other .md files and start the full implimentation" - 2026-10-22.
