# FIX PLAN — verified defect backlog and remediation phases

**Status:** in progress. W1 (P0-1 packaging) and its side-fix (P1-11
hermeticity) are **implemented and reviewed**; the rest is unimplemented. Each
fixed item is marked **FIXED (Wn)**; the wave table at §7 tracks progress.

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

### P0-4 A search-provider outage is reported as CONVERGED [V]

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

**Fix**

- `retrieval.py` must distinguish *failed* from *empty*: record a per-query
  failure and a `search_failures` counter; do not mark a failed query as
  successfully executed. Per-query isolation is correct — one bad provider must
  not kill the loop — but the **aggregate** must not lie.
- `convergence.py` must consume `search_failures` and return
  `PROVIDER_DEGRADED` when retrieval was attempted and failed, even if
  `fetch_failures == 0`.
- `core/orchestrator.py` must surface the new counter in the stats dict it
  passes to the analyzer.

**Regression test.** `tests/invariants/test_convergence_semantics.py`: search
provider raises for every query ⇒ `stop_reason == PROVIDER_DEGRADED`, **not**
CONVERGED. Add the mutation to `scripts/mutation_check.py` (per AGENTS.md §11:
mutation first for gates) — mutate the new guard and require detection.

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
passes: 292 passed, 1 skipped. Before the fix, the same tree failed
`tests/integration/test_phase4_integration.py::TestPlatformEndToEnd::test_full_flow_services_only`.


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
| **W1** | P0-1 packaging (+ P1-11 hermeticity side-fix) | Unblocks clean installs and the container; independent of everything else | **DONE**: wheel contains 16/16 template files; `research doctor` exits 0 from a clean install; `scripts/check_dist.py` passes; 292 passed / 1 skipped; zero outbound sockets |
| **W2** | P0-2 auth bypass | With D-3 this is the *only* auth boundary; must land before the container runs anywhere real | **DONE**: 401 without a token on a real `0.0.0.0` bind; INV-014 row + M-7/M-8/M-9 mutations all DETECTED |
| **W3** | P0-4 failure≠empty (search) | Small, self-contained, unblocks honest convergence reporting | New convergence test + mutation M-10 detected |
| **W4** | P0-5 sandbox escape | Security; self-contained | Override-write test green; existing sandbox suite green |
| **W5** | P0-3 ULID migration | Now a one-function change, but it touches every entity creation path indirectly — needs its own wave and a full-suite run | Restart test green; monotonicity test green; `data_repair` ordering test green; full suite green |
| **W6** | P0-6 config honesty (D-2) | Needs the provider registry; implement the gate, delete `respect_robots` | New test: LOCAL_ONLY ⇒ no network providers registered; unknown mode ⇒ LOCAL_ONLY |
| **W7** | P1-1…P1-7 | Contract/correctness batch; each is small | Per-item tests + full suite |
| **W8** | P2-1/P2-2 test harness + property layer | Prevents recurrence of the BUG-03/BUG-06 class | Conformance suite green |
| **W9** | P2-3…P2-7 dead code, doc drift | Cleanup; do it after behaviour is correct so the docs describe the final state | `scripts/reaudit.py` still 14/14; `mutation_check.py` still 9/9+ |
| **W10** | P3-1…P3-9 metric honesty | Changes measured numbers; needs mutation-first | Each scorer has a mutation in `mutation_check.py` that is detected |

**Per wave, the AGENTS.md §2 workflow applies**: context subagent → atomic
phase → independent review subagent → tests → next phase. No wave is declared
done on a green suite alone.

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
