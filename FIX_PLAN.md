# FIX PLAN — verified defect backlog and remediation phases

**Status:** **W1 through W10 (Phases 0–6) are implemented and verified across
all local gates (`pytest`, `mutation_check.py` M-1..M-26, `reaudit.py` 14/14,
`check_dist.py`, `run_eval.py --offline`, `run_goldset.py`).** See
`IMPLEMENTATION_STATUS.md` for the four-state verification matrix (implementation,
focused regression, full-gate validation, and review status).

| Wave | Item | Result | Verified by |
|---|---|---|---|
| W1 | P0-1 packaging | The wheel ships all 16 template files and declares `fastapi`/`uvicorn`; a clean install runs `research doctor` | `scripts/check_dist.py`, `tests/unit/test_packaging.py` |
| W1 | P1-11 hermeticity | The suite no longer reads the developer's `gar.yaml`; **zero** outbound sockets measured | socket-level probe over the suite |
| W2 | P0-2 auth bypass | `research serve --host 0.0.0.0` now requires `X-API-Token`; the bind address and the authorised address are the same value (INV-014) | real uvicorn on `0.0.0.0`, 401/401/200 |
| W3 | P0-4 failure ≠ empty | A search outage yields `PROVIDER_DEGRADED`, never `CONVERGED`; providers raise, the failure is recorded on the query row | end-to-end through the real orchestrator |
| — | P1-8…P1-10, P1-12…P1-16 | found during the waves, still open | see §2 |

**Decisions taken by the owner (2026-10-20):**

| # | Decision | Consequence for this plan |
|---|---|---|
| D-1 | **Entity IDs become prefixed ULID** (not seed-from-DB, not UUID4) | P0-3 rewritten as a ULID migration |
| D-2 | **Implement the `privacy_mode` / `local_only` guarantee; retract `respect_robots`** | P0-6 split into "implement the gate" + "delete the robots promise" |
| D-3 | **Loopback API stays unauthenticated** | P0-2 narrows to the bind-address mismatch only; S-01 is not a defect to fix |

D-3 has a consequence worth stating plainly: with loopback open by design, the
**only** thing standing between a developer machine and a full research API is
the bind address. That makes P0-2 (the app checking the *configured* host
instead of the *actual* bind address) the sole authentication boundary, so it
must be airtight — no other partial fix is acceptable.

**How this list was derived.** The repo's audit reports (`BUG_AUDIT.md`,
`SECURITY_AUDIT.md`, `ARCHITECTURE_AUDIT.md`, `TEST_GAP_ANALYSIS.md`,
`RESEARCH_QUALITY_AUDIT.md`, `BAD_DECISIONS.md`, `SYSTEM_REASSESSMENT.md`) are
pre-stabilization and carry no status markers. Their claims were re-verified
against the current source; several are already fixed, and the fixes themselves
introduced new problems. Evidence is tagged:

- **[V]** — independently reproduced in this session (code path traced or
  executed).
- **[S]** — verified by a read-only subagent with file:line evidence, not
  independently reproduced by me.
- **[D]** — doc claim only; not verified. Treated as a hypothesis.

`scripts/reaudit.py` reports 14/14, but it only replays BUG-01…BUG-06,
BUG-08/09/10 and P0-01…P0-13. It does not cover BUG-07, BUG-11…BUG-16 or
S-01…S-06. **A green `reaudit.py` is not evidence that the backlog is clear.**

---

## 0. Findings that are already closed (do not re-open)

| ID | Verdict | Evidence |
|---|---|---|
| BUG-01/02/03/04/05/06/08/09/10, P0-01…P0-13 | Fixed | `scripts/reaudit.py` 14/14, exit 0 |
| BUG-07 FTS dup on re-save | Fixed | `storage/database.py:437-444` DELETE+INSERT; `tests/invariants/test_bugfix_regressions.py:14-32` |
| BUG-11 EventBus drop counter | Fixed (partial) | `platform/events.py:71,96-110` counter+warning; persistence failures still swallowed (see P2-6) |
| S-02 prompt-injection delimiters | Partially fixed | Untrusted fences present in 8 prompt metas; no source-allowlist weighting for planner queries (P2) |

---

## 1. P0 — silent correctness / security failures

### P0-1 The shipped image cannot start, and would be an open API if it could [V] — **FIXED (W1)**

**Root cause (three defects stacked):**

1. `pyproject.toml:12-19` did not declare `fastapi`/`uvicorn`, but
   `api/app.py:15` and `cli/main.py:961` import them.
2. `pyproject.toml` had no `[tool.setuptools.package-data]`. Built wheel
   contained **0 of 16** files under `prompts/templates/**` →
   `prompts/registry.py:41` raised `FileNotFoundError` for every prompt.
3. `Dockerfile:13` `CMD ["research","serve","--host","0.0.0.0","--port","8000"]`
   — the exact path of P0-2.

Verified: `uv build --wheel` → the baseline wheel had 142 files, 0 template
files, no `fastapi` requirement. A clean install of that wheel could not run `research serve`
(`No module named 'uvicorn'`) or `research doctor` (`No module named 'fastapi'`).
After the fix the same wheel has 158 files (142 + the 16 template files).

**Fix (implemented in W1)**

- Declared `fastapi>=0.100.0` and `uvicorn>=0.15.0` in `[project.dependencies]`.
  Floors are evidence-based: `fastapi` 0.100.0 is the first release with
  pydantic-v2 support and provides every symbol used; `uvicorn` is used only
  via `uvicorn.run` (`cli/main.py:971`), 0.15.0 is the floor.
- Added `[tool.setuptools.package-data]` with
  `"research_engine.prompts" = ["templates/*/*.txt", "templates/*/*.meta.yaml"]`.
  The key **must stay quoted** — unquoted it is a TOML nested table, and
  setuptools rejects the build with
  `ValueError: invalid pyproject.toml config: ... must be array`.
- `prompts/registry.py`: a missing templates directory now raises an
  actionable "installation is incomplete" error instead of a bare
  `FileNotFoundError` from `iterdir()` (`record_versions()` aborted project
  creation at `core/orchestrator.py:70`).

**Rejected during review:** adding `providers/embeddings/__init__.py`. The
package already ships (setuptools' `namespaces = true` is the documented
default for `packages.find`), so the file was not required by the fix and was
speculative hardening — removed.

**Regression coverage**

- `tests/unit/test_packaging.py` (4 tests): every third-party import under
  `src/` is a declared dependency; every template file is covered by a
  package-data glob; every template loads with a non-empty system prompt (a
  missing `.meta.yaml` silently yields an empty system prompt); a missing
  templates dir reports an incomplete installation.
- `scripts/check_dist.py`: builds a wheel, asserts the 16 templates are in it,
  asserts `fastapi`/`uvicorn` are in the metadata, and extracts the wheel and
  proves it loads 8 templates and imports the API module. Passes.

**Note.** The editable install is what hid this defect; the new tests assert
the *source of truth* (`pyproject.toml`) so they run in the fast unit suite,
and `check_dist.py` asserts the built artifact.

---

### P0-2 API auth bypass on an external bind [V] — **FIXED (W2)**

**Root cause.** `api/app.py:426-429` decides "is this external?" from
`ctx.cfg.platform.api.host` (the *configured* host). `cli/main.py:962` binds
`args.host` (the *CLI override*). The two disagree.

`research serve --host 0.0.0.0` with `platform.api.auth_token` set (the only
way to get past the startup guard at `cli/main.py:963-969`):

- startup guard: host `0.0.0.0` is non-local → token is configured → proceeds
- request guard: configured host is `127.0.0.1` → `external = False` →
  **no token required**

Result: the API serves every endpoint, unauthenticated, on all interfaces.
`Dockerfile:13` ships exactly this invocation. Existing tests
(`tests/security/test_security.py:72-108`) only cover the non-loopback case and
miss the override entirely.

**Fix (implemented in W2)**

- `cli/main.py cmd_serve` now writes the effective bind address into
  `ctx.cfg.platform.api.host` **before** `create_app(ctx)`. The app therefore
  authorises on the address that was actually bound, not on the configured one.
- `core/config.py` gained `is_loopback_host()` — one shared, **fail-closed**
  predicate (loopback IPv4/IPv6 + `localhost`; everything else, including a
  wildcard bind, is external). The literal loopback tuple was previously
  duplicated in `app.py` and `cli/main.py`, which is how the two sides drifted.
- `api/app.py make_auth_dependency` now resolves the context through the same
  lazy getter the routes use. Previously a `create_app()` without an explicit
  context could **never** require a token (the holder was still `None` when
  the dependency ran) — a latent way to disable the only auth boundary.
- The token is compared with `secrets.compare_digest` (constant time).

**Why the config-carried address and not the ASGI scope.** Measured against
real uvicorn: `scope["server"]` is the *per-connection local address* (equal
to the address the client dialled — on a `0.0.0.0` listener it reads
`127.0.0.1` for a loopback client, i.e. it misclassifies exactly the dangerous
case), `request.url.hostname` reflects the spoofable `Host` header, and
`request.client.host` is the *caller*. Only the binding process knows the
listener's address.

**Regression coverage**

- `tests/invariants/test_api_auth_boundary.py` (INV-014, 6 tests): loopback
  needs no token (pins D-3); an external bind rejects a missing/wrong token
  on the real request path; only provably loopback addresses are trusted;
  **the `--host 0.0.0.0` override is the address the app authorises on** (the
  original defect); an external bind without a token is refused *before*
  anything binds; an app created without an explicit context still enforces
  the token.
- `scripts/mutation_check.py` gained **M-7** (the CLI stops propagating the
  effective address), **M-8** (the app treats every bind as loopback) and
  **M-9** (the dependency reads the raw context holder instead of resolving
  it) — all DETECTED.
- `GET /events/stream` is now auth-gated: the feed carries every event type,
  so on an external bind it must not be an open pipe. Only `/health`,
  `/ready`, `/info` and FastAPI's own `/docs`, `/redoc`, `/openapi.json` stay
  open (verified by AST enumeration of every route).
- Verified end-to-end against a **real** uvicorn server bound to `0.0.0.0`
  while the configured host was `127.0.0.1`: no token → 401, wrong token →
  401, correct token → 200.
- `docs/invariants.md` gained the INV-014 row; `docs/api.md`,
  `docs/security.md`, `docs/deployment.md` and `README.md` were reconciled
  (the "external binding requires a token" claim is now true).

**Known gap (not fixed here).** `cmd_serve` ignores the global `--config`
flag — it uses the ambient/global context, so a token set in the `--config`
file is not seen. Tracked as P1-12.

---

### P0-3 Entity IDs collide across processes and silently destroy rows → migrate to ULID [V]

**Root cause.** `core/ids.py:12-17` `next_id()` is a **process-global counter**
with no persistence. `core/ids.py:21` `seed_counter()` exists to re-seed it and
has **zero callers and no test**. `storage/database.py:397-400` upserts with
`ON CONFLICT(id) DO UPDATE` — a colliding ID **overwrites** the existing row.

Reproduced across two processes: both wrote `ev_000001`; the database ended with
**1 row** — the first evidence was destroyed. Same for claims, hypotheses,
sources, experiments and graph entities.

**Decision D-1: switch entity IDs to prefixed ULID.**

**Blast radius (verified) — small, because `next_id()` is the single funnel.**
`models/base.py:29` (`self.id = next_id(prefix or self.PREFIX)`) and
`storage/graph_store.py:110-112` are the only call sites outside it.

- Nothing in `src/`, `tests/`, `scripts/` or `evals/` parses the numeric suffix
  of an entity ID (grepped `split("_")`, `int(...id)`, `[1:]` — no hits).
- **No test asserts the ID format.**
- Report filenames are static (`evidence_map.md`, …); only the research-log
  header embeds `project.id`.
- `storage/graph_store.py:148,178` (`ORDER BY id`) and
  `specialists/startup/data_repair.py:72-77` (`ORDER BY id` ⇒ "the oldest row
  of each duplicate group sorts first") both depend on **id order == creation
  order**. ULID preserves that; a random UUID4 would silently break it.
  → ULID, not UUID4. (This is also why the monotonic variant is mandatory
  below.)

**Design**

- **Keep the type prefix** (`ev_`, `clm_`, `ent_`, `opp_`, …). It is load-bearing
  for type discrimination in repos, natural keys, graph prefixes and CLI
  output. Only the sequential number is replaced.
- New format: `<prefix>_<26-char Crockford base32 ULID>`, e.g.
  `ev_01HQ8XM3K7P9R4T2V6Y0Z1A3B`.
- **Monotonic ULID**: within one millisecond, increment the random component so
  IDs are strictly increasing in creation order. Without this,
  `data_repair`'s "oldest duplicate wins" becomes non-deterministic within a
  millisecond and INV-003 ("natural-key upserts keep original identity") loses
  its determinism guarantee.
- Implement in `core/ids.py` (~25 lines: 48-bit ms timestamp + 80-bit
  randomness, Crockford alphabet, monotonic increment). **No new dependency.**
- Delete `core/ids.py:21` `seed_counter` — obsolete, zero callers, no test.

**Compatibility with existing data.** Old rows keep `ev_000001`; new rows are
`ev_01H…`. `ORDER BY id` puts legacy rows first (digits sort before uppercase),
so legacy-then-new ordering stays chronological. **No migration, and none
should be written**: re-keying existing rows would break the
evidence → claim → source traceability chains in already-published reports
(AGENTS.md §13).

**Regression test**

- Two `Orchestrator` instances in **separate processes** against the same
  project DB ⇒ disjoint ID sets and the row count grows by 2, not stays at 1.
- `next_id()` is strictly increasing within a process, including for 10 000 IDs
  generated inside one millisecond (monotonicity).
- IDs match `<prefix>_[0-9A-HJKMNP-TV-Z]{26}` (Crockford: no I, L, O, U).
- `data_repair` dedupe still keeps the **oldest** member of a duplicate group.

**Risk:** medium-low for the code (one function), medium for operator
expectations (IDs get longer; `research trace-claim <id> clm_000001` in
`README.md` needs updating). No table, index or natural-key change.

---

### P0-4 A search-provider outage is reported as CONVERGED [V] — **FIXED (W3)**

**Root cause.** Two halves:

- `pipeline/retrieval.py:66-68` — a provider exception is caught, logged, and
  converted to `hits = []`. The query is still marked `executed=True`
  (`retrieval.py:45-46`). **A failed search and a search that found nothing are
  indistinguishable.** (INV-012 violation at the search boundary.)
- `reasoning/convergence.py:61-63` — `PROVIDER_DEGRADED` requires
  `fetch_failures > 0`, and `fetch_failures` is derived from *document* rows
  (`core/orchestrator.py:382,575`). A search outage creates no document rows, so
  `fetch_failures == 0`.

Executed: a search outage (8 queries, 0 fetch failures, 12 evidence) returns
`StopReason.CONVERGED` — "new evidence rate 0/12 below threshold". A total
search outage is reported as successful research. This directly contradicts
INV-006, and `docs/invariants.md:13` states the invariant as if it holds.

`tests/invariants/test_convergence_semantics.py:36-46` only exercises the
*fetch*-failure case, so the invariant suite stays green while INV-006 is
violated. This is exactly the "test that does not test the thing" failure the
audit warned about.

**Fix (implemented in W3)**

The investigation showed the defect was **deeper than the plan assumed**: the
existing `PROVIDER_DEGRADED` guard could never fire in production.

- `fetch_failures` was structurally always 0 — a fetch failure marks the
  **Source** row, so no Document row is ever written with a non-PARSED
  status. The real fetch-failure counter is `sources_rejected`.
- `queries_executed` was always 0 in the executing iteration (queries carry
  their *creation* iteration).
- The failure was destroyed one layer above the code that needed it: every
  provider swallowed the error and returned `[]`, so `retrieval.py`'s own
  handler rarely even saw an exception.

So the fix had to make the whole chain honest:

- `providers/search/base.py`: new `SearchProviderError`; the contract now
  says a provider **raises** on failure and returns `[]` only for a
  successful search that found nothing.
- `providers/search/duckduckgo.py` + `providers/academic/*.py`: raise instead
  of returning `[]`. DuckDuckGo distinguishes "every attempt failed" from
  "a 200 response with no hits"; a 429 rate limit is a failure, not an empty
  result.
- `pipeline/retrieval.py`: the worker records the failure on the query row
  (`failed`, `failure_reason`) instead of flattening it. A cache hit and a
  provider that was never configured are **not** failures — counting those
  would report an intentional offline run as an outage.
- `models/research.py`: `SearchQuery.failed` / `.failure_reason` (JSON-only,
  like `results_count`; counted in Python, no schema migration).
- `core/orchestrator.py`: `retrieval_failures` = Δ(search failures) +
  Δ(fetch failures), replacing the two metrics that were always zero.
- `reasoning/convergence.py`: the guard is now
  `new_evidence == 0 AND retrieval_failures > 0` ⇒ `PROVIDER_DEGRADED`. A
  failure implies an attempt, so no separate "attempts" term is needed.

**Regression coverage**

- `tests/invariants/test_search_failure_semantics.py` (NEW, 14 tests) — the
  chain the old suite never exercised: a provider that raises is recorded on
  the query row; a search that succeeded and found nothing is NOT a failure;
  an unconfigured provider is NOT a failure; **every in-tree provider honours
  the raise contract** (parameterised over all six); a rate limit is a
  failure; **a total outage through the real orchestrator yields
  `PROVIDER_DEGRADED`, never `CONVERGED`**.
- `tests/invariants/test_convergence_semantics.py`: the old outage test now
  uses the real key, plus a search-outage case and a "failures with progress
  are not degradation" case. The keys the analyzer no longer reads were
  removed so the dicts state the real contract.
- `scripts/mutation_check.py`: **M-2** re-anchored to the new condition;
  **M-10** (the worker stops recording the failure), **M-11** (the DuckDuckGo
  wrapper swallows it again) and **M-12…M-15** (the same, per academic
  provider file) added — 15/15 DETECTED.
- `docs/invariants.md` INV-006/INV-012 enforcement columns, `docs/convergence.md`
  and `docs/failure_handling.md` updated: both invariants were **false as
  written** before this change. INV-012's row now names the one boundary
  that is still open (the watcher — P1-14).

**Review outcome (independent reviewer).** No blockers. Five SHOULD-FIX
items, all addressed: the four academic providers had no contract coverage
(now parameterised + M-12…M-15); "an unconfigured provider is not a failure"
was untested (now a test); `docs/failure_handling.md` overstated the
guarantee (now qualified — degradation needs *zero new evidence*); the W1 row
of this plan had been overwritten with W3's test count (restored); the
convergence tests still passed the dead stats keys (removed).

---

### P0-5 Experiment sandbox write-root is rebindable from user code [V]

**Root cause.** `experiments/runner.py:37` puts the allowed write root in a
module global of the guard script, and `runner.py:73` `exec()`s user code in
**that same namespace**. The hook reads `_ALLOWED_WRITE_ROOT` as a global at
call time, so user code can rebind it:

```python
globals()["_ALLOWED_WRITE_ROOT"] = "/tmp"   # sandbox write guard now permits /tmp
```

Reproduced: `/tmp/gar_escape_test4.txt` was created, exit code 0. The audit's
original framing (`GAR_EXPERIMENT_WORKDIR` trust) no longer applies — that env
var is read once at guard-install time — but the escape is real and worse.

`tests/experiments/test_experiments.py:50-56` only covers a plain
outside-the-workdir write; the override case is untested.

**Fix.** The root and the network-deny flag must be bound into the hook's
**closure/default arguments** at definition time, in a module the user code
cannot rebind — not looked up in exec-visible globals. Move the guard into a
dedicated module (e.g. `experiments/_sandbox_guard.py`) whose values are
captured as `def _guard(event, args, _root=..., _deny_net=...)` defaults, and
import it from the child rather than inlining it into the exec namespace.

**Regression test.** Add to `tests/experiments/test_experiments.py`: experiment
code that sets `globals()["_ALLOWED_WRITE_ROOT"] = "/tmp"` and writes there ⇒
`PermissionError`, and the file must not exist afterwards.

**Risk:** medium — the guard is the sandbox's core. Verify the existing sandbox
suite (`tests/experiments/`, `tests/security/`) still passes, including the
"allows ssl import" case noted in `BUG_AUDIT.md` §Cleared suspicions.

---

### P0-6 `LOCAL_ONLY` / `privacy_mode` are decorative [V]

**Root cause.** `core/config.py:107-108` define `security.local_only` and
`security.privacy_mode`. Their only reader is `effective_environment()`
(`config.py:133-138`), called from exactly one place — `api/app.py:86`, a
display field. `core/orchestrator.py:640-662` `build_default_registry()`
registers DuckDuckGo + 4 academic providers with **no environment check**.

Verified: with `platform.mode: local` (⇒ `effective_environment()` returns
`LOCAL_ONLY`), the registry still contains `['web']` search and
`['openalex','crossref','arxiv']` academic providers. The API reports
`environment=LOCAL_ONLY` to the client while the engine makes outbound calls.

Aggravating: `core/config.py:138` maps any **unrecognised** mode to `"HYBRID"` —
the most permissive — so a typo (`mode: local_only`) *upgrades* the environment
instead of failing closed. `gar.example.yaml:80` and `docs/configuration.md:25-26`
both promise "privacy_mode: true ⇒ zero external calls". `gar.example.yaml:39`
promises `respect_robots: true`, which is also never implemented.

**Fix (D-2: implement the gate; retract `respect_robots`)**

- **Implement** `local_only` / `privacy_mode` as a real network gate:
  `build_default_registry()` (`core/orchestrator.py:640-662`) and the provider
  factory (`providers/llm/router.py:27-33`) must consult the effective
  environment and register **no** network providers when it is `LOCAL_ONLY`.
  A local LLM (`ollama` / `openai_compatible` on localhost) and
  `embeddings.provider: hashing` must remain available in that mode.
- **Fail closed** on an unrecognised `platform.mode`: `core/config.py:138`
  currently maps unknown values to `HYBRID`, the most permissive. Unknown ⇒
  `LOCAL_ONLY` (plus a logged error), not `HYBRID`.
- **Retract `respect_robots`**: `core/config.py:54` and `gar.example.yaml:39`
  promise robots.txt handling that is not implemented. Delete the knob and the
  example line, or implement it — retracting is the honest choice at this
  stage. Do **not** leave the promise in place.
- The API's `environment` field (`api/app.py:86`) becomes truthful once the
  gate exists, which is what makes it useful rather than decorative.

**Regression test**

- With `platform.mode: local` (⇒ `LOCAL_ONLY`): the provider registry contains
  **no** web/academic provider, and a network call attempt is refused.
- With an unrecognised `platform.mode`: the effective environment is
  `LOCAL_ONLY`, not `HYBRID`.
- `respect_robots` no longer appears in `AppConfig` nor in `gar.example.yaml`.

---

## 2. P1 — correctness, honesty, contract

### P1-1 Unknown LLM provider silently becomes MockProvider [V]
`providers/llm/router.py:27-33` falls back to `MockProvider` on an unknown
provider string; `core/config.py:16-24` has no validator on the provider field.
A typo (`provider: ollamma`) yields a research run that reports "no evidence
found" instead of a configuration error. **Fix:** validate the provider name in
`LLMRoleConfig`; hard-fail unless the effective environment is offline and the
provider is `mock`. **Test:** unknown provider ⇒ raises (not mock).

### P1-2 Three LLM tasks are prompted as a search-query generator [S]
`specialists/startup/assumptions.py:93`, `reasoning/methodology_designer.py:172`
and `intelligence/falsification.py:44` all call `get_prompt("query_generator")`,
whose system prompt is *"You generate search queries for a research engine"* —
role-specific and actively wrong for these three tasks. Invisible under
`MockProvider`. **Fix:** add versioned templates
`prompts/templates/{assumption_generator,methodology_designer,falsification_designer}/v1.txt`
+ `.meta.yaml` (AGENTS.md §14: add v1, never edit v1). **Test:** assert each
task renders its own template, and that no template named `query_generator` is
used outside `pipeline/`.

### P1-3 `structured()` "never raises" is half-true; 3 callers turn outages into empty results [S]
`providers/llm/base.py:40-61` retries schema failures but propagates transport
errors. `reasoning/methodology_designer.py:189-190`,
`specialists/startup/assumptions.py:105-106`, `intelligence/falsification.py:100-101`
swallow that into "no output" — INV-012 violated at the LLM boundary.
**Fix:** these sites must distinguish provider failure from empty output and
record the failure.

### P1-4 Two incompatible API error envelopes [S]
`api/app.py:396-399` emits `{"error": {...}}`; 7 sites raise
`HTTPException(detail={"error": {...}})` (`:202,210,223,232,240,249,433`) which
FastAPI renders as `{"detail": {"error": {...}}}`. `docs/api.md:57-61`
documents only the first. **Fix:** one envelope, applied everywhere; update
`docs/api.md`.

### P1-5 `list_projects()` omits fields its consumers read [S]
`services/research_service.py:82-85` returns only `{id, question, state, mode,
updated_at}`. `mcp_server/server.py:482` reads `x["created_at"]` ⇒ **KeyError**
on the MCP startup-reuse path; `cli/main.py:673` reads `question_raw` ⇒ always
`""` ⇒ the "reuse existing project" branch never matches (duplicate projects);
`api/app.py:320`, `mcp_server/server.py:265`, `cli/main.py:657` read
`created_at` ⇒ always `""` ⇒ "latest startup project" is arbitrary.
**Fix:** return the fields; decide the authoritative definition of "latest"
(created_at vs updated_at) and use it consistently. **Test:** MCP
`startup_discover_opportunities` twice ⇒ same project reused, no crash.

### P1-6 The per-project audit trail is not redacted [S]
`platform/obs_logging.py:19-33` redacts, but `storage/events.py:23-49` writes
`metadata`/`error` verbatim to `events.jsonl` and `reports/research_log.md`
(e.g. `core/orchestrator.py:164` `error=str(exc)[:500]`). Also
`core/config.py:111` `security.redact_secrets_in_logs` is read by nobody while
redaction is unconditional. **Fix:** apply redaction in the event persister;
delete the dead flag or wire it.

### P1-7 Config traps: ignored keys and a permissive default [S]
- `gar.example.yaml:4` top-level `mode: academic` is silently ignored — the
  real field is `research.mode` (`config.py:34`). A user setting `mode: startup`
  at the top level silently gets `academic`.
- `core/config.py:138` maps unknown `platform.mode` → `HYBRID` (most
  permissive). Fail closed instead.
- 12 config knobs are read nowhere (incl. `network.respect_robots`,
  `resources.max_parallel_llm_tasks` cited in `docs/architecture.md:51`).
**Fix:** correct the example; fail closed on unknown mode; delete or wire the
dead knobs.

### P1-8 `render()` crashes on untrusted content that contains `{{...}}` [V] — **OPEN, found during W1**

**Root cause.** `prompts/registry.py:24-34` substitutes the supplied kwargs
into the template and then scans the **rendered** output for
`{{snake_case}}` placeholders. The comment above it claims "braces inside
untrusted document content must never crash the pipeline" — the code does not
implement that: it raises `ValueError` for any unfilled lowercase placeholder,
**including one that arrived inside a value**.

Reproduced:
```python
get_prompt("query_generator").render(branch_question="b", required_evidence="e",
                                     context="{{unknown_var}}", n_queries=3)
# -> ValueError: unknown/unfilled placeholder 'unknown_var' in prompt query_generator
```

The existing test (`tests/security/test_security.py:19-30`) passes only
because it injects `{{chunk_text}}` — a name that *is* in `kwargs`. It proves
tolerance of one specific placeholder, not general tolerance.

**Impact.** Scraped document text reaching a template as a *value* can abort
the evidence worker (`pipeline/evidence.py:149-152` passes `chunk_text`), the
planner (`pipeline/planning.py:157-159` passes `context`), the gap detector
(`reasoning/gap_detector.py:102-105`) or the synthesiser
(`reports/synthesis.py:32-39`). None of those call sites wraps `render()` in a
try/except. A single document containing `{{some_word}}` kills the run — a
remote-content-triggered failure, and an INV-012 violation (external content
is UNTRUSTED).

**Fix.** Determine "which placeholders are ours" from the **raw template**,
not from the rendered output: collect the placeholder names present in
`self.template`, then raise only for those that were not supplied. Braces that
came in through a value are then never mistaken for our placeholders. Also
move the `import re` in that method to module level.

**Regression test.** `tests/unit/test_packaging.py` or a new
`tests/unit/test_prompts.py`:
- a value containing `{{unknown_var}}` renders without raising, and the text
  survives verbatim;
- a *template* placeholder that is not supplied still raises `ValueError`
  (the guard must not be weakened into a no-op).

### P1-9 Prompt version selection picks `v2` over `v10` [V] — **OPEN, low**

`prompts/registry.py:43` selects the latest version with
`sorted(p.stem for p in base.glob("v*.txt"))[-1]` — a **lexicographic** sort, so
with `v1, v2, v10` present it picks `v2`. No v2 exists today, so this is
latent, but it will bite the first time a prompt reaches a double-digit
version. Same pattern at `registry.py:68` in `record_versions()`.

**Fix.** Sort numerically on the digits after the `v` prefix, and keep the
stored value consistent with `PromptSpec.version` (which stores `"1"`, while
`record_versions()` currently stores `"v1"`).

**Regression test.** A temp template dir with `v1`, `v2`, `v10` ⇒ the
selected version is `v10`.

---
### P1-10 The env-override walker silently corrupts list-valued settings [V] — **OPEN, found during W1**

`core/config.py:182-208` `apply_env_overrides()` coerces `bool`/`int`/`float`
and assigns everything else as a raw string. A list field therefore becomes a
**string**:

```
GAR_SEARCH__ACADEMIC_PROVIDERS=[]   ->  cfg.search.academic_providers == '[]'   (a str, not a list)
```

`for name in cfg.search.academic_providers` then iterates *characters*. In this
case no academic provider matches, so it accidentally behaves like "none" —
which is exactly the kind of luck that hides a bug. A list containing a real
provider name (e.g. `openalex`) would iterate its characters and register
nothing, silently disabling the provider.

**Fix.** Parse the raw value as JSON when the field annotation is a list/tuple
(`json.loads`), falling back to the raw string only if the annotation is a
plain string. Reject a malformed value loudly rather than assigning it.

**Regression test.** `GAR_SEARCH__ACADEMIC_PROVIDERS=[]` ⇒ the field is `[]`
(a list); `GAR_SEARCH__ACADEMIC_PROVIDERS=["openalex"]` ⇒ `["openalex"]`.

### P1-11 The test suite was not hermetic — it read the developer's `gar.yaml` [V] — **FIXED (W1)**

**Root cause.** `AppConfig.load()` reads a CWD-relative `gar.yaml`. The shipped
`gar.example.yaml` selects the `ollama` provider, and `scripts/setup_dev.sh`
copies it into place. `tests/conftest.py` built its configs with
`AppConfig.load()` — so the moment the documented setup had been run, the
suite constructed a **real** `OllamaProvider` and a test died with
`ConnectError: [Errno 111] Connection refused` instead of exercising the code
under test. The "fully offline" guarantee held only while no `gar.yaml`
existed.

**Fix**

- `tests/conftest.py` pins `GAR_MODELS__{EXTRACTOR,REASONING,SYNTHESIS}__PROVIDER=mock`
  and `GAR_SEARCH__WEB_PROVIDER=none` at import time. Env overrides have the
  highest precedence in `AppConfig.load()`, so this covers every config load,
  including the ones inside production code (`services/context.py`,
  `platform/job_runners.py`).
- The `cfg` fixture additionally clears `search.academic_providers` (it
  already cleared `web_provider`).
- `.gitignore` now ignores `gar.yaml` / `gar.yml` / `config/gar.yaml` — the
  documented setup created an untracked file that showed up in `git status`.
- `.env.example` now states that the engine reads the *environment*, not the
  `.env` file (nothing loads it; there is no dotenv dependency).

**Verification.** With `gar.yaml` present (provider `ollama`), the suite now
passes: 308 passed, 1 skipped. Before the fix, the same tree failed
`tests/integration/test_phase4_integration.py::TestPlatformEndToEnd::test_full_flow_services_only`.

### P1-12 `research serve` ignores the global `--config` flag [V] — **OPEN, found during W2**

`cli/main.py cmd_serve` obtains its config from the global context
(`_ctx4()` → `AppConfig.load()` with no path), so the documented global flag
`research --config <file> serve ...` has **no effect**: the operator's token,
host and port in that file are never seen by the guard, the bind, or the app.
Verified: `research --config <file with host 0.0.0.0 + auth_token> serve
--host 0.0.0.0` still refused to start.

**Fix.** `cmd_serve` should load the config from `--config` (the same
`_cfg(args)` path the other commands use) and build its context from it.

**Risk.** Medium: `cmd_serve` currently shares the *global* context with the
rest of the process. Switching to a per-invocation context changes identity
semantics for anything that reads the global context while the server runs.
This is why it was not folded into W2.

### P1-13 The "forum" route leg resolves to a provider that does not exist [V] — **OPEN, found during W3**

`pipeline/retrieval.py:82` maps only `("documentation", "government",
"company")` to the `web` provider, while the comment on the line above says
*"documentation / government / **forum** are web-search refinements"*. So the
`forum` refinement resolves to a provider literally named `forum`, which is
never registered ⇒ `ProviderRegistry.get_any("forum")` returns `None` ⇒ the
lookup returns nothing.

`pipeline/routing.py` has `DEFAULT_ROUTES["PAIN"] = ["web", "forum"]`, so
**the forum leg of the PAIN branch — a primary signal source in startup mode
— has always returned zero results, silently.** (The W3 fix deliberately
does NOT count a missing provider as a failure, so this stays invisible.)

**Fix.** Map `forum` to the `web` provider as the comment says, and make the
route→provider mapping explicit rather than a literal tuple in the worker.

### P1-14 The watcher boundary still flattens a provider failure [V] — **OPEN, found during W3**

`platform/watchers.py:154-157` calls a search provider and swallows every
exception (`except Exception: pass`), then records `status: "OK", new: 0` — a
total outage looks like "no new sources found". The same file's academic
leg at `:163` calls `reg.academic.get(name)`, but `ProviderRegistry` has no
`academic` attribute (only `_academic`, `get_any`, `get_search`) ⇒ an
`AttributeError`, swallowed by `except Exception: continue` ⇒ **the watcher's
academic search has never run**.

INV-012 names "every external boundary"; this one is still open, which the
invariant row now says explicitly.

**Fix.** Use `reg.get_any(name)`; record the failure on the watcher run
(status/reason) instead of "OK"; and report the watcher outcome honestly.

### P1-15 A search backend that blocks bots now reports a failure, not "no results" [V] — **OPEN, behaviour change**

DuckDuckGo's HTML endpoints commonly answer `403`/`202` to bots. Those are
non-200 responses, so the provider now raises `SearchProviderError` instead of
returning `[]`. A live run against a bot-blocked endpoint therefore reports
`PROVIDER_DEGRADED` where it used to report "no results" — and, because the
failure is now counted, it can stop the run earlier.

This is the honest reading (the search did not happen), but it is a real
behaviour change for live runs and it is documented in
`docs/failure_handling.md`. If it proves too noisy in practice, the fix is a
SearXNG instance (`gar.example.yaml` recommends one) — not a re-hiding of
the failure.

### P1-16 A 200 response that is not a result page still reads as "found nothing" [V] — **OPEN, low**

`providers/search/duckduckgo.py`: a `200` whose body is not a result page (a
bot-challenge, a layout change) sets `served = True`, so the provider returns
`[]` — the honest "the backend answered, there was nothing in the answer"
reading, but the *parse* silently produced nothing. Closing this needs the
provider to tell "no results" from "not a result page" (e.g. require DDG's
no-results marker). Deliberately not done in W3; the current behaviour is
pinned by a test so it cannot drift unnoticed.


## 3. P2 — test integrity, dead code, doc drift

### P2-1 No interface conformance harness [S]
`TEST_GAP_ANALYSIS.md` §Structural gaps #1: nothing invokes *every* API route
and *every* MCP tool. BUG-03 and BUG-06 (two shipped-broken tools) are exactly
this class. **Fix:** a parametrized smoke test that calls every registered route
and tool through the service seam with offline fakes; any `TypeError`/500 fails.
Pair it with a test asserting `docs/api.md` and `docs/mcp.md` list every
registered route/tool (8 `/startup/*` routes and 14 `startup_*` tools are
currently undocumented).

### P2-2 Property/invariant layer missing [S]
Candidate invariants that nothing asserts today: `evidence.status=REJECTED ⇒
excluded from aggregators`; `claims.supported_by` ids exist; `fts_rows ==
evidence_rows`; terminal jobs never transition; `build_market_context` row
count stable; opportunity without evidence ⇒ notes contain `SPECULATIVE`.

### P2-3 Silent `except` blocks that hide real failures [S]
34 sites in `src/`. The ones that matter:
- `pipeline/retrieval.py:66-68` (P0-4)
- `storage/platform_db.py:397-398, 412-413` — a corrupt task row silently
  vanishes from `stale_tasks`, so crash recovery never sees it
- `platform/events.py:138-139, 153-154` — audit persistence failure invisible
- `services/context.py:63-65` — `EventPersister` construction failure ⇒ the
  process runs with **no audit persistence at all**, silently
- `specialists/startup/assumptions.py:105-106` (P1-3)
- `intelligence/falsification.py:100-101` (P1-3)
- `core/orchestrator.py:161-162` — an illegal transition inside the fatal
  handler is swallowed; the project can stay non-FAILED while `stop_reason`
  says FAILED

### P2-4 `assert` used for runtime logic [S]
`storage/platform_db.py:248` (`assert task is not None` right before
`task.status = ...` — under `python -O` this becomes an `AttributeError` on
`None` while holding the DB connection) and `services/context.py:78`. Replace
with explicit error raising.

### P2-5 Dead code / duplicate engines [S]
- 17 unreferenced top-level symbols; 2 fully unimported modules
  (`modes/base.py`, `reasoning/novelty.py`)
- Duplicate class definitions: `NotFoundError`/`ConflictError` shadowed within
  `services/research_service.py`; `Assumption` and `ResearchQuestion` defined
  in both `models/project.py` and `models/reasoning.py`; `RetryPolicy` in both
  `core/retry.py` and `platform/errors.py`; `TaskStatus` in both
  `models/enums.py` and `models/job.py`
- **Three money parsers** — `specialists/startup/policies.py:237`,
  `specialists/startup/competitors.py:26`, `specialists/startup/market.py:26` —
  while `docs/invariants.md:18` (INV-011) claims "one canonical money parser".
  The invariant is stated as holding; it does not. Either consolidate or amend
  INV-011 to describe reality.
- `platform/resilience.py` (circuit breakers, rate limits, failover) is
  imported by **nothing** in `src/` — test-only. `docs/architecture.md:102`
  claims it wraps provider chains. False.
- `core/retry.py` is live but used only by `pipeline/fetching.py`;
  `platform/errors.py`'s policy table is dead.
- `evals/runners/run_eval.py:38` — `if not hasattr(...) or True:` (a tautology
  masking intent, per `SYSTEM_REASSESSMENT.md` §17)

### P2-6 Doc drift (false claims) [V/S]
`docs/architecture.md:102` (resilience), `:25` ("`structured()` never raises"),
`:92` (trace ids — `new_trace_id` is dead); `docs/configuration.md:25-26`
(privacy); `docs/invariants.md:13` (INV-006, see P0-4) and `:18` (INV-011,
see P2-5); `docs/api.md:21-61`; `docs/mcp.md:19-32`; `docs/development.md:3,7,14-20`
(`python3 -m venv` fails here; "40 tests, ~3s" — actual 284 tests / ~110s);
`docs/failure_handling.md:32-36` (retry table disagrees with
`platform/errors.py:42` and `providers/llm/base.py:41`); `README.md:57,152`
("80 tests").

### P2-7 Events and observability gaps [S]
`dropped_events` is not surfaced in `/health` or metrics; persistence failures
are not counted; per-project audit events are not redacted (P1-6).

---

## 4. P2/P3 — research-quality honesty (BD-04 / BD-06)

| ID | Issue | Evidence |
|---|---|---|
| P3-1 | `citation_coverage` is a plumbing tautology — fraction of claims with non-empty `supported_by`, never read from report text; a report citing nothing scores 1.0 | `evals/metrics/eval_metrics.py:91-93` [S] |
| P3-2 | `research_gain` counts rows, not information (+0.5/accepted row) — one press release across 10 domains yields gain ≈16 | BD-04 [S] |
| P3-3 | `dup_count` telemetry is always 0 (initialised, never incremented) | `pipeline/evidence.py:199` [S] |
| P3-4 | Hypothesis confidence floored at 0.25 with zero support — an unevidenced hypothesis shows non-trivial confidence | `reasoning/hypothesis_engine.py` [S] |
| P3-5 | `RefinementLoop` sets `.status` directly, bypassing `ALLOWED_HYPO_TRANSITIONS` — the exact pattern AGENTS.md forbids | `reasoning/hypothesis_engine.py:552` [S] |
| P3-6 | Funding vocabulary leaks into payment-class demand evidence: `pain_evidence_class("Invoice-automation startup raises $20M") == "actual_payment"` | `specialists/startup/policies.py:37,54` [S] |
| P3-7 | P4 opportunity severity is a hardcoded `0.45`, not evidence-derived | [S] |
| P3-8 | BUG-14 hypothesis tie-bias toward generation order (no `ORDER BY` + stable sort ⇒ first-generated wins every tie) | `reasoning/hypothesis_engine.py:506,525` [S] |
| P3-9 | BUG-16 `decisions.readiness` counts experiments across opportunities ⇒ inflated `VALIDATION_READY`. `models/reasoning.py:135-151` `Experiment` has **no** `opportunity_id` ⇒ needs a schema change (`SCHEMA_VERSION` bump + `_migrate`) | `specialists/startup/decisions.py:48` [S] |

**Note.** P3-1…P3-7 change measured research-quality numbers. Any change to a
scorer or metric needs the mutation added to `scripts/mutation_check.py`
*first* (AGENTS.md §11), so the gate is proven to detect the regression it
guards.

---

## 5. P3 — small known items

- **S-03** unknown provider ⇒ hard fail (folded into P1-1).
- **S-04** `GAR_EXPERIMENT_WORKDIR` / `GAR_EXPERIMENT_NETWORK` read at import
  time and undocumented in `.env.example` / `gar.example.yaml`;
  `config.experiments.network_enabled` is read for the manifest only
  (`experiments/runner.py:158`) while the guard uses the env var. Fold into
  P0-5.
- **S-05** MCP stdio: `mcp_server/server.py:559-571` reads lines with no
  max-length guard. Accepted risk, but a 1 MB line limit is cheap.
- **S-01** loopback auth default — **not a defect** (D-3: loopback stays
  unauthenticated by design). The consequence of D-3 is recorded under P0-2:
  the bind-address check is now the only auth boundary, so it must be airtight.
- **D05** process-global ID counter restart hazard — see P0-3.
- **D22** `freshness_summary` has zero callers; many entities persist empty
  `observed_at` ⇒ "unknown" forever.
- `core/ids.py:21` `seed_counter` — wired by P0-3.
- `storage/repositories.py:234-239` `ReportRepo` — never read or written.

---

## 6. Decisions resolved

**D-1 — Entity IDs become prefixed ULID.** See P0-3. Rejected alternatives:
seed-from-DB (leaves multi-process collisions reachable, and keeps a fragile
numeric suffix); DB-backed sequence (correct, but needs a schema migration and
a project-aware allocator for a problem a ULID solves in one function);
plain UUID4 (random ordering breaks `data_repair`'s "oldest duplicate wins" and
`graph_store`'s `ORDER BY id`). ULID keeps the `ev_`/`clm_` prefix vocabulary
and the creation-order property the code already relies on.

**D-2 — Implement the `privacy_mode` / `local_only` gate; retract
`respect_robots`.** Rejected: retracting the whole promise (a local-first
product that silently calls out is worse than one that does not, and the call
sites are few — `build_default_registry` plus the provider factory).
`respect_robots` is retracted because honouring robots.txt needs a real
implementation (fetch-time policy per host) and that is not a small change; a
promise the code cannot keep is worse than no promise.

**D-3 — Loopback API stays unauthenticated.** Rejected: flipping the default to
"token always required" (friction on a single-user local tool, and the audits
themselves call the current default "right for dev"); "require the token
whenever one is configured" (a middle ground that closes P0-2's "token ignored"
case, but the underlying defect — the app checking the configured host while
the CLI binds a different one — is the same defect and must be fixed either
way). Accepted consequence: the bind-address check is the entire auth
boundary, so P0-2 is a P0 and gets an explicit regression test.

---

## 7. Proposed execution order

| Wave | Scope | Why this order | Gate |
|---|---|---|---|
| **W1** | P0-1 packaging (+ P1-11 hermeticity side-fix) | Unblocks clean installs and the container; independent of everything else | **DONE**: wheel contains 16/16 template files; `research doctor` exits 0 from a clean install; `scripts/check_dist.py` passes; 292 passed / 1 skipped at the time of W1; zero outbound sockets |
| **W2** | P0-2 auth bypass | With D-3 this is the *only* auth boundary; must land before the container runs anywhere real | **DONE**: 401 without a token on a real `0.0.0.0` bind; INV-014 row + M-7/M-8/M-9 mutations all DETECTED |
| **W3** | P0-4 failure≠empty (search) | Small, self-contained, unblocks honest convergence reporting | **DONE**: a total outage through the real orchestrator yields PROVIDER_DEGRADED; M-2 re-anchored, M-10..M-15 added; 308 passed / 1 skipped |
| **W4** | P0-5 sandbox escape | Security; self-contained | **DONE**: Closure-isolated write root in `experiments/runner.py`; `test_sandbox_override_write.py` green |
| **W5** | P0-3 ULID migration (`C07`, `C08`, `C22`) | Collision-free monotonic ULIDs + payload `created_at` ordering | **DONE**: `core/ids.py` monotonic ULIDs, `M-19` DETECTED, `test_stage2_id_ordering.py` green |
| **W6** | P0-6 config honesty & egress (`C09`–`C12`, `C23`) | Enforced `EgressPolicy` across all HTTP call sites & redirect hops; `respect_robots` removed | **DONE**: `test_egress_enforcement.py` (24 tests) and `test_local_only_gating.py` green |
| **W7** | P1-1…P1-16 | Config/provider/CLI truthfulness, dedicated prompt templates, API error schema, DTOs, redaction, search failure semantics | **DONE**: `test_phase2a_config_providers.py`, `test_phase2b_prompts_llm.py`, `test_phase2c_api_dto_redaction.py`, `test_phase2d_duckduckgo_parsing.py` green; wheel ships 22 template files |
| **W8** | P2-1/P2-2 + Stage 4 (`C13`–`C16`) | Dynamic 43-route API & 30-tool MCP conformance + docs parity; property-style invariants; analyst review overlay | **DONE**: `test_interface_contracts.py`, `test_system_invariants.py`, `test_stage4_review.py` green |
| **W9** | P2-3…P2-7 + Phase 6 | Silent-except & `assert` removal, canonical money parser, doc drift, `/health` events check, MCP 1 MiB line cap, `freshness_summary` & `ReportRepo` wiring | **DONE**: `test_phase3_resilience_health.py` & `test_phase6_transport_freshness.py` green; `reaudit.py` 14/14 |
| **W10** | P3-1…P3-9 + Stage 5 (`C17`–`C21`, `C24`) | Research-quality metrics, deduplicated `research_gain`, `dup_count` wiring, hypothesis lifecycle/tie-break, funding vs payment, P4 strength, `Experiment.opportunity_id` | **DONE**: `test_phase5_research_quality.py` green; `M-1`..`M-26` (26/26) DETECTED; `run_eval.py --offline` 17/17 PASS |

**Per wave, the AGENTS.md §2 workflow applies**: context subagent → atomic
phase → independent review subagent → tests → next phase. No wave is declared
done on a green suite alone.

**Stage→wave mapping** (from `docs/plans/2026-10-22-evidence-pipeline-and-analyst-review.md` §E):
| Plan stage | Scope | Maps to FIX_PLAN wave |
|---|---|---|
| Stage 1 | Dead legs, honest counts (C01-C06) | P1-13, P1-14 (+ new) |
| Stage 2 | Collision-free ids (C07, C08, C22) | P0-3 (W5) |
| Stage 3 | Enforced egress (C09-C12, C23) | P0-6 (W6) |
| Stage 4 | Analyst review (C13-C16) | new |
| Stage 5 | Quality benchmark (C17-C21, C24) | new (P3-1...P3-9 partial) |

**Sequencing note.** W5 (ULID) is deliberately *after* W1–W4: those waves add
entities and rows, and doing the ID migration first would mean re-verifying
their tests against two ID formats. W5's own regression tests pin the format,
so nothing after it depends on the old one.

---

## 8. Explicitly out of scope (and why)

- **New specialists, modes, UI, distributed workers** — `STABILIZATION_REPORT.md`
  §8: do not build until the suspected issues are resolved and the debt list
  shrinks.
- **Replacing SQLite / adding vector DBs** — no evidence of a current need.
- **Rewriting the evidence model** — the grounding gates (P0-4 aside) work;
  P3-1…P3-3 are metric-layer fixes, not model changes.
- **Resolving `SYSTEM_REASSESSMENT.md` §25 "remaining unknowns"** — those need
  live runs with real models, not code changes.
