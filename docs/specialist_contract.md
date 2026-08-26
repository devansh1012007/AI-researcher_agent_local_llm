# Specialist Contract

Authoritative checklist for what a specialist provides vs inherits.
Enforcement: `tests/specialists/test_contract_harness.py` runs EVERY
registered specialist through the harness automatically (§77).

## A specialist defines

```text
specialist_id · name · version (semver-ish)
supported_modes · input/output schema descriptions
source_preferences · research_policies (incl. routing keywords)
evidence_requirements · entity_types · scoring_models
skills (versioned prompt pieces) · report_templates
evaluation_suite path · permissions · budgets · model_routing hints
```

## The platform guarantees (no specialist code needed)

identity (natural keys + UNIQUE backstops) · grounding (both gates inside
`SpecialistApi.create_evidence`) · task ownership/fencing/retry via the
scheduler · project isolation (`SpecialistApi._scope`) · report purity ·
score schema validation (INV-010 shape) · budgets · audit trail +
performance registry.

## Hard rules

1. Specialists receive ONLY `RunContext` (orchestrator handle is for reads
   through the api facade; storage construction is scan-forbidden — INV-014).
2. Every write goes through permissioned API methods that route the canonical
   validation pipeline. No raw repos, SQL, filesystem escapes.
3. More research is requested via `CREATE_RESEARCH_TASK` — the orchestrator
   schedules it; specialists never fetch/network themselves.
4. Outputs are `SpecialistOutput`; claims/gaps created during the run are
   already persisted artifacts — output lists reference ids.
5. Confidence values in outputs are derived from persisted evidence quality;
   specialists never assert trustworthiness directly.

## New-specialist checklist

- [ ] descriptor complete (harness asserts fields non-empty)
- [ ] policies module pure & offline-deterministic where possible
- [ ] skills as versioned prompt files if LLM steps added
- [ ] contract harness passes end-to-end via SPECIALIST_TASK
- [ ] eval dataset under `evals/specialists/<id>.json` w/ thresholds
- [ ] golden suite once stable
