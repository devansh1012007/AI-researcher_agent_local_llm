# Policy Registry

Versioned adaptive policies live in `platform.sqlite::policies`
(natural key kind+version) managed exclusively through
`adaptive/policies.PolicyRegistry` via `services/quality_service.QualityService`.

## Kinds

| kind | baseline body | what may adapt |
|---|---|---|
| `routing` | rules-only, ε=0 | weights, exploration ε (≤0.15), bounds within hard caps |
| `query_strategy` | tie_break_only | family boosts applied to low-stakes strategy ties |
| `model_routing` | observe-only | role→candidate preferences + fallback actions (advisory v1) |
| `research_depth` | fixed budget | enables dynamic iteration budgets (§47/§48), requires explicit activation |

## Lifecycle

```
draft ──record_evaluation──► canary ──activate (human)──► active ──► retired
  ▲                                                                      │
  └──────────── rollback == activate(most recent retired) ◄──────────────┘
```

- `baseline` versions ship ACTIVE and are IMMUTABLE — they describe shipped
  behavior. Proposing `baseline` raises.
- Activation REFUSES bodies violating hard caps (max_adjustment, ε>0.15).
- Every activation/deactivation writes an `adaptive_decisions` audit row.
- Canary = recorded offline evaluation on a benchmark subset BEFORE any
  human sees an activation decision (§54).

## Commands

```bash
research policy list [kind]
research policy show <kind> <version>
research policy propose <kind> <version> --body '{...}'
research policy evaluate <kind> <version> --evaluation '{"routing_accuracy":0.85}'
research policy activate <kind> <version> --reason "bench A/B won"
research policy rollback <kind> --reason "regression detected"
research policy deactivate <kind>
research policy compare <kind> --version-a v1 --version-b v2
```

API: `GET /policies`, `POST /policies {action}` · MCP: `list_policies`,
`activate_policy`.

## Rollback triggers (§91)

Citation-quality drop, grounding failures, research-gain fall, or cost rise
beyond threshold ⇒ `rollback` returns the platform to the last known-good
version; `deactivate` returns to shipped-baseline. Both are one command and
fully audited.
