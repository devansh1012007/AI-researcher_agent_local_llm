# Testing Strategy

Layers:
1. Unit/integration suites (offline fakes; quotes always derive from chunks).
2. Invariant suite `tests/invariants/` — every docs/invariants.md item has a
   named adversarial test (single-writer fencing, idempotency, purity,
   faithfulness, convergence, isolation, boundaries, contracts).
3. Interface conformance: every API endpoint + MCP tool executes through the
   service seam; wiring crashes (TypeError class) fail loudly.
4. Mutation testing: `scripts/mutation_check.py` — known-critical mutations
   (gate threshold, convergence branch, support mapping, upsert resolve,
   fence check, weighting formula) MUST be detected; exit code gates.
5. Re-audit harness: `scripts/reaudit.py` replays every original audit
   reproduction; CI-runnable proof that fixed defects stay fixed.

Rule: a green suite is evidence tests pass, not proof of correctness —
when changing scorers/gates/state machines, add the mutation first.
