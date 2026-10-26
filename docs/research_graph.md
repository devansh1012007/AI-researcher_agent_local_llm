# Research Graph

Phase 1 stored evidence as rows. Phase 2 stores **relationships** between entities.

## Storage

Relational, not a graph DB (spec #69): `graph_entities` + `graph_relationships` tables
in the same SQLite database. Entities are typed nodes with JSON attributes; relationships
are typed edges with confidence + evidence provenance.

```
entity types: paper · source · concept · company · competitor · pain_point
              market_signal · price_observation · opportunity
edge types:   extracted_from · supports_claim · contradicts · mentions
              evaluated_on · extends · compares · uses · signals · priced_at ...
```

## Builder (`pipeline/graph_builder.py`)

Runs after each research cycle. Deterministic edges only:
- evidence → source (`extracted_from`)
- claim → evidence (`supports_claim`, mirrors Claim.supported_by)
- contradiction pairs (`contradicts`)
- papers → benchmarks/datasets from extractor tags (`evaluated_on`)
- sources → capitalized concepts found in claims (`mentions`, deduplicated)

Entity resolution: same project+type+normalized-name collapses to one node. Normalization
is conservative (drops Inc/LLC suffixes) — under-merging is preferred over wrong merges;
ambiguity is preserved.

## Queries answered by the graph

- `evidence_density(type)` — which papers/companies carry the most evidence
- `neighbors(entity_id)` — what connects to this entity and why
- startup intelligence persists its entities here (one store for Phase 2 models)
