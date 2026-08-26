# Specialist Ecosystem (Phase 5)

Many specialized ways of reasoning; ONE coherent system of truth. Specialists
contribute domain intelligence; the platform owns state, evidence, execution,
security, provenance, scheduling and invariants.

## Architecture

```
            Orchestrator ──── SpecialistRegistry (capability catalog)
                 │                    │
     SPECIALIST_TASK jobs (fenced scheduler tasks)
                 │
   SpecialistApi (permissioned seam: grounding gates,
                  budget counters, project isolation)
                 │
   Shared evidence · claims · gaps · entities · connections
                 │
        Cross-domain synthesis (read-only)
```

- **No second state machine** — specialist invocations are ordinary
  `SPECIALIST_TASK` platform tasks: lease, fencing token, retry, cancellation
  and audit all inherited.
- **Hybrid routing** — deterministic domain-signal rules select; an optional
  schema-validated LLM step may veto/annotate; rules stand when no LLM is
  available. Selection reason is stored on every task (`specialist_reason`).
- **Composition** — workflow templates order stages (`RESEARCH_GAP_TO_STARTUP`
  = literature → technology → startup); stage boundaries are structured
  `Handoff`s (evidence/claim ids, constraints, open questions), never
  transcripts.
- **Cycle guard** — a re-invocation without research gain since the
  specialist's last run is SKIPPED with reason.
- **Limits** — ≤5 specialists per project; per-invocation budgets
  (queries/documents/llm/time) hard-stop work.

## Built-in set

| id | pipeline |
|---|---|
| literature@1.0 | map → method comparison → gap detection |
| technology@1.0 | constraint extraction → coverage scoring → risk register |
| competitive@1.0 | landscape (shared startup competitor tables) → pricing comparison → change detection |
| foresight@1.0 | trend scan → enabling/disruptive direction → impact mapping |
| startup@1.0 | adapter over `StartupResearchService` modes |

Finance is deliberately deferred (spec §20): current core lacks the
strong-numerical-provenance machinery it deserves; revisit after INV-011-class
temporal provenance work.

## Cross-domain layer

- `Connection` rows (INV-003 natural key source/target/relationship) carry
  linked evidence, COMPUTED confidence (canonical INV-007 aggregator) and a
  validation status governed by domain standards:
  - RESEARCH→MARKET requires technical ∧ customer ∧ market evidence (§61)
  - PROBLEM→SOLUTION requires problem ∧ feasibility evidence (§62)
- Cross-specialist contradictions reuse the Contradiction row additively
  (`CROSS_DOMAIN_*`, specialist_a/b) preserving INV-009 both-sides integrity.
- Synthesis is READ-ONLY: per-dimension confidence matrix (technical / market /
  customer / competition / distribution / regulatory kept separate), weakest-
  dimension research queue, integrated findings with provenance ids.

See also: `docs/specialist_contract.md`, `docs/cross_domain_research.md`,
`docs/specialist_security.md`, `docs/specialist_evaluation.md`.
