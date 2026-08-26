# Extension Invariants (INV-014)

## INV-014 — Specialist persistence contract

> A specialist persists domain entities only through repo seams that declare
> identity (natural key + UNIQUE backstop), never opens storage itself, and
> cannot feed ungrounded evidence into synthesis unnoticed.

**Why:** the stabilization phase made the core invariant-safe, but nothing
stopped a *future* specialist from reintroducing every fixed bug class
(duplicate entities, ungrounded claims, unfenced tasks, mutating reports).
INV-014 turns the extension contract into executable checks so future
specialist mistakes are caught automatically (gate §50).

### Enforcement (two halves)

1. **Static scan** — `tests/invariants/test_extension_contract.py::TestInv014StaticScan`
   Forbids `Database(`, `sqlite3.connect(`, and raw `.upsert(` inside
   `specialists/**` except the documented allowlist:
   `kb.py` (cross-project KB owns its store), `data_repair.py` (maintenance,
   passed-in handle), `extension_audit.py` (auditor itself).

2. **Runtime auditors** — `src/research_engine/specialists/extension_audit.py`
   - `ungrounded_evidence(db, project_id=None)` — flags evidence rows that
     feed synthesis (SUPPORTED/WEAKLY_SUPPORTED) lacking `support_verdict`
     and outside `GROUNDED_EXEMPT_SOURCE_TYPES`, plus any non-REJECTED row
     with an empty quote. REJECTED rows are audit trail, never violations.
   - `validate_score_schema(breakdown)` — rejects opaque scores; requires
     `schema_version == 2` and named dimensions each carrying a reason.
   - `store_fingerprint(paths)` — WAL-safe LOGICAL content hash of SQLite
     stores (byte-hashing misses committed-but-uncheckpointed writes);
     used by purity tests and golden-run baselines.

Consumers today: the invariant suite. Planned consumers: golden runners
(both modes) so every regression run re-audits grounding and score schema
over real pipeline output.

### Decision: detectors now, enforcement later

# Decision: INV-014 ships as auditors consumed by tests, not as runtime
# blocking inside repo save paths.
# Why: hard-blocking would immediately trip on the existing experiment-result
# ingestion path (gate finding F-03) — i.e., it would be a behavior fix
# smuggled into a report-only phase.
# Constraint: promotion to enforcement happens together with resolving F-03
# (settle the provenance carve-out, then move checks into the canonical
# write seam and flip the negative fixtures from detector-based to
# exception-based assertions).

### Mutation-testing note

INV-014 guards are structural scans/detectors, not formulas; there is no
arithmetic to mutate. The formula-bearing neighbors (rubric gating, support
factor) remain covered by `scripts/mutation_check.py`. If INV-014 is later
promoted into runtime enforcement, add a mutation that weakens the write-seam
check and make `mutation_check.py` detect it.

### Adding the next invariant

Follow `docs/invariants.md` §"Adding a new invariant": one sentence, named
enforcement, unit + adversarial tests, mutation if formula-bearing.
