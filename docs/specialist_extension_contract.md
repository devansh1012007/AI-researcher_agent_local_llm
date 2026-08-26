# Specialist Extension Contract

What a new specialist provides vs what the platform guarantees. This is the
authoritative checklist for adding e.g. a Legal, Healthcare, or Financial
researcher without forking the platform. Enforcement mechanics live in
`docs/extension_invariants.md`; system invariants in `docs/invariants.md`.

## The split

| A specialist PROVIDES | The platform OWNS |
|---|---|
| domain policies (`specialists/<dom>/policies.py`, pure functions) | scheduler, leases, fencing, retry (`platform/`, `storage/platform_db.py`) |
| entity models + `PREFIX` + natural keys | evidence store, quote + claim-support grounding gates |
| source preferences / provider routing config | project state machine, budgets |
| analyzers over repos data | identity resolution & merge (`identity.py`, `_GenericRepo.save_natural`) |
| report templates (markdown writers, derived-only) | report orchestration; read-only generation guarantee |
| scoring rubric (named dimensions + reasons) | opportunity schema versioning (`schema_version=2`) |
| eval tasks + quality thresholds | eval runner, metrics, failure semantics |

A specialist must NOT create its own: evidence storage, claim validation,
scheduler/task lifecycle, identity scheme, report mutation path, MCP/API
plumbing, or a second scoring/persistence schema for a concept that exists.

## Integration steps

1. Create `specialists/<domain>/` with `models.py` (entities extend
   `models/base.Entity`, declare `ClassVar[str] PREFIX`), `repos.py`
   (`_GenericRepo` subclass per entity **with `natural_key()`**, bundle via
   the `get_<dom>_repos(orch)` idiom), `policies.py` (pure functions).
2. Register tables in `Database._EXTRA_TABLES`; add UNIQUE indexes to
   `_STARTUP_UNIQUE_INDEXES`-equivalent list when a natural key is
   database-expressible.
3. Add modes to your `<Domain>Service.run_mode`; consume everything through
   `Orchestrator.load` / application services — never construct `Database`,
   `Repositories`, or call `StateMachine.transition`.
4. LLM outputs flow: model → parser → schema validation → semantic
   validation → business rules → persistence. Claims additionally pass BOTH
   grounding gates (`pipeline/evidence.verify_quote`,
   `pipeline/claim_support.verify_claim_support`) before any status that
   feeds synthesis.
5. Reports are derived: read repos, render markdown. If more research is
   needed, emit a research request to the orchestrator — never mutate.
6. Scores go through a versioned rubric (`schema_version=2`, named
   dimensions, each dimension score+reason). No opaque numbers.
7. Add eval tasks under `evals/datasets/` and, once stable, a controlled
   corpus under `evals/golden/<domain>/`.

## New persisted entity checklist (§33)

Before adding an entity answer, in writing:

- What is its identity? (natural key function, normalization rules)
- What is its lifecycle? (who creates/mutates/retires it)
- Which relationships does it own? (foreign links kept consistent on merge)
- What service owns its mutation? (one authoritative write path)
- Which invariants apply? (idempotency, grounding of linked evidence…)
- How is it migrated and repaired? (`data_repair` story for legacy rows)
- Idempotency test: same analysis ×N ⇒ same identities, no duplicate rows;
  concurrent writers ⇒ UNIQUE index backstop holds.

## New long-running task checklist (§35)

Tasks submitted through `PersistentScheduler.submit_job` automatically get
job identity, atomic claim, lease + renewal thread, fencing token
(`attempts`), stale-writer rejection, retry with backoff, cancellation and
terminal-absorbing state. Anything a specialist runs OUTSIDE the scheduler
must either move inside or document its own ownership story — convention
does not count.

## Violation → detection map (§50)

| Mistake | Caught by |
|---|---|
| direct DB/storage construction in interface layers | `test_system_invariants.py::TestServiceBoundaries` scan |
| specialist opens its own DB / raw upserts | `test_extension_contract.py::TestInv014StaticScan` |
| duplicate entity writes bypassing natural key | DB UNIQUE indexes → IntegrityError |
| ungrounded evidence reaching synthesis | INV-014 `ungrounded_evidence` auditor (invariant suite + goldens); becomes hard enforcement after F-03 resolution |
| task write without valid fence | `StaleTaskOwner` at PlatformDB layer |
| mutating "report" writer | store fingerprint guard (`extension_audit.store_fingerprint`) in purity tests/goldens |
| opaque score | `validate_score_schema` auditor; report writers render only versioned rubrics |

## Known exceptions

- CLI legacy loaders `_load2/_load3` (read handles) and ops tools
  (`data_repair`, KB store, `extension_audit`) are allowlisted seams.
- Experiment-result provenance currently enters evidence without
  claim-support verification — tracked as gate finding F-03; do not copy
  that pattern into new specialists.
