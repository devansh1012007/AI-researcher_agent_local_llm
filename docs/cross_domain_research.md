# Cross-Domain Research

How specialists compose and how connections between domains earn trust.

## Pipelines

- **research→startup (flagship, §60/§79)**: literature → technology →
  startup → validation. Stages run as fenced platform tasks chained by
  structured handoffs (`workflows.run_flagship`).
- **startup→technology (§26)**: customer pain → technical constraint →
  feasibility — expressed via `CUSTOMER_PAIN_TO_TECHNOLOGY` connections plus
  a technology stage.

## Connection lifecycle

```
PROPOSED ── standards met (evidence classes) ──► VALIDATED
    │                                              ▲
    └── alternatives exist ∧ unmet classes ──► CONTESTED
```

- Natural key `(source_entity, target_entity, relationship)` — INV-003.
- Confidence = canonical aggregator (INV-007) over linked evidence; empty
  evidence ⇒ 0.0. Specialists cannot inflate it (INV-015).
- Standards: RESEARCH_TO_MARKET / RESEARCH_GAP_TO_STARTUP need
  technical+customer_problem+market; CUSTOMER_PAIN_TO_TECHNOLOGY needs
  problem+technical_feasibility. Fail-closed.

## Contradictions across specialists

Recorded as `Contradiction(conflict_type=CROSS_DOMAIN_*, specialist_a=…,
specialist_b=…)` with BOTH evidence sides (INV-009). Synthesis surfaces open
cross-domain contradictions; nothing silently resolves them.

## Consensus & confidence

Consensus is EVIDENCE-WEIGHTED through `aggregate_claim_strength`: three weak
analyses never outvote one strong one. Per-domain confidences stay separate
(§63) and feed the decision matrix:

```
technical / market / customer / competition / distribution / regulatory
        each: confidence + signal count + HIGH/MEDIUM/LOW/UNKNOWN label
weakest_dimensions_queue → next research actions (§65)
```

A synthesized finding always carries its provenance chain ids
(opportunity/connection → evidence_ids), so no cross-domain leap is presented
as fact without support (§41/§80).

## Interfaces

- CLI: `research specialists <pid>`, `research cross-domain <pid>`,
  `specialists [id]`
- API: `GET /projects/{id}/specialists`,
  `POST /projects/{id}/cross-domain-research`
- MCP: `start_cross_domain_research`, `list_specialists`
