# Continuous Intelligence (Phase 6)

The platform learns **which research actions reliably produce better
evidence and better decisions under these constraints** — through
measurement and versioned policy, never self-modification (spec §2).

## The control loop

```
RESEARCH → MEASURE → EVALUATE → LEARN → PROPOSE POLICY
   ▲                                        │
   │                              OFFLINE EVALUATION
   │                                        │
   └── MONITOR ◄── DEPLOY ◄── HUMAN ACTIVATION ◄─┘
```

Hard rules enforced in code:

1. **No autonomous deployment path exists.** Learning writes `draft`
   policies; only an explicit human command (`research policy activate`,
   API `POST /policies {action: activate}`, MCP tool) deploys.
2. **Bounds are hard caps** (`adaptive/policies.BASELINE_ROUTING`):
   routing score adjustment ≤ ±0.15, exploration ε ≤ 0.15, reliability
   floor ≥ 0.5, min 5 samples before any learning applies. Activation
   REFUSES out-of-bounds bodies.
3. **Cold start is inert.** With no history, routing v2 == routing v1
   bit-for-bit; goldens stay deterministic.
4. **Learning sits beneath every invariant** (INV-001…016). It can never
   touch grounding, fencing, isolation, or reports.

## Where things live

| Concern | Store |
|---|---|
| Research outcomes (§6 record) | `platform.sqlite::research_outcomes` |
| Policy versions + lifecycle | `platform.sqlite::policies` |
| Query-family / source-type utility | `query_family_perf` / `source_perf` |
| Model performance (per call telemetry) | `llm_perf` |
| User feedback (separate from objective quality) | `user_feedback` |
| Inspectable decisions ("why X?") | `adaptive_decisions` |
| Critic reviews / ranked alerts | `research_reviews` / `research_alerts` |

See also: `adaptive_routing.md`, `research_learning.md`,
`policy_registry.md`, `evaluation_data.md`, `research_quality.md`,
`self_critique.md`, `change_impact.md`.
