# Phase 7 — Production Learning Architecture (actual implementation)

Implemented surfaces (not hypothetical):
- Persistence: LearningDB (learning/persistence.py) with DDL for observations, dataset_snapshots, learning_runs, candidate_policies, canary_metrics, policy_activations, freeze_states.
- Eligibility: EligibilityFilter (learning/eligibility.py) excludes synthetic, future observations, duplicates; preserves provenance.
- Learning: LearningRun (learning/learning.py) bounded surfaces, deterministic seed, fingerprint, freeze check.
- Candidate: CandidatePolicy (learning/candidate.py) lifecycle states, parent/dataset linkage, evaluation/regression metrics, rollback target.
- Evaluation: evaluation.py requires train/eval separation; detects leakage.
- Safety: SafetyGate (learning/safety.py) requires authorization_ref, checks frozen state, verifies rollback target.
- Invariants: INV-017..025 documented in docs/invariants.md; enforced by persistence schema + SafetyGate + eligibility filter.
- No autonomous activation path exists (verified by grep; SafetyGate.can_activate always requires external authorization_ref).
- No self-modifying production code (learning only writes candidate/dataset/run tables; never rewrites source).
- Human approval remains explicit in policy_activations (activated_by, approved_by, authorization_reference).

Not implemented (deliberately excluded per §43/§44):
- No online parameter mutation inside live decision path.
- No distributed training, vector DB, online RL, autonomous code generation, or autonomous deployment.
- No unrestricted learning on security/auth/deployment surfaces (§10).
