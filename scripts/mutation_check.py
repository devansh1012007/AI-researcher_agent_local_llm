#!/usr/bin/env python
"""Mutation testing harness (stabilization spec §57).

Applies each known-critical mutation to the source, runs its targeted test
subset, reverts, and reports whether the suite DETECTED the mutation.

Usage:
    python scripts/mutation_check.py            # run all mutations
    python scripts/mutation_check.py M-1 M-5    # run a subset

Exit code 0 iff every mutation was detected.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (id, file, old_snippet, new_snippet, targeted_tests)
MUTATIONS = [
    ("M-1", "src/research_engine/specialists/startup/opportunities.py",
     'priority = ("high" if len(missing) <= 2 and not speculative and demand_ok',
     'priority = ("high" if len(missing) <= 9 and not speculative and demand_ok',
     "tests/invariants/test_system_invariants.py::TestOpportunitySchema"),

    ("M-2", "src/research_engine/reasoning/convergence.py",
     '''        if (new_ev == 0 and fetch_failures > 0 and queries_executed > 0):''',
     '''        if (False):''',
     "tests/invariants/test_convergence_semantics.py::TestFailureVsConvergence::test_provider_outage_is_not_convergence"),

    ("M-3", "src/research_engine/pipeline/claim_support.py",
     '''    if verdict in ("CONTRADICTS", "UNRELATED"):
        return EvidenceStatus.REJECTED''',
     '''    if verdict in ("NEVER",):
        return EvidenceStatus.REJECTED''',
     "tests/invariants/test_claim_faithfulness.py::TestIntegration::test_status_mapping_fail_closed"),

    ("M-4", "src/research_engine/storage/reasoning_repos.py",
     '''        existing = self.find_by_natural_key(entity.project_id, key)
        if existing is not None:''',
     '''        existing = None
        if False:''',
     "tests/invariants/test_entity_identity.py::TestBug02Idempotency::test_natural_key_resolution_keeps_identity"),

    ("M-5", "src/research_engine/storage/platform_db.py",
     '''        if fence is not None and current.attempts != fence:
            raise StaleTaskOwner(task_id, worker_id,
                                 current.attempts, fence,
                                 reason="fencing token mismatch")''',
     '''        if False:
            pass''',
     "tests/invariants/test_single_writer.py::TestFencing"),

    ("M-6", "src/research_engine/reasoning/hypothesis_engine.py",
     '''    if sup:
        weights = [_ev_weight(e) for e in sup]
        best_single = max(weights)''',
     '''    if sup:
        weights = [_ev_weight(e) for e in sup]
        best_single = min(1.0, sum(weights) / 3.0 + 0.35 * (len(weights) // 3))''',
     "tests/invariants/test_claim_faithfulness.py::TestHypothesisWeighting"),

    # Phase 5 §47/§87: routing selection logic must be load-bearing
    ("M-7", "src/research_engine/specialists/routing.py",
     '''        hits = sorted({k for k in kws if k in text})
        if hits:''',
     '''        hits = sorted({k for k in kws if k in text})
        if False:''',
     "tests/specialists/test_orchestration.py::TestHybridRouting"),

    # Phase 6 §97: adaptive-layer mutations MUST be detected
    ("M-8", "src/research_engine/adaptive/routing_v2.py",
     '''    adjusted.sort(key=lambda s: -s.score)''',
     '''    adjusted = [next(s for s in adjusted
                     if s.specialist_id == base[0].specialist_id)] + \\
        [s for s in adjusted if s.specialist_id != base[0].specialist_id]''',
     "tests/adaptive/test_routing_v2.py::test_history_adjusts_within_clamp_only_on_ties"),

    ("M-9", "src/research_engine/adaptive/routing_v2.py",
     '''    if runs < min_runs:
        return None     # not enough evidence to adjust anything (§10)''',
     '''    if False:
        return None     # not enough evidence to adjust anything (§10)''',
     "tests/adaptive/test_routing_v2.py::test_min_samples_gate_prevents_overfit"),

    ("M-10", "src/research_engine/adaptive/routing_v2.py",
     '''    explored = ""
    if eps > 0 and len(adjusted) >= 2 and \\''',
     '''    explored = ""
    if False and eps > 0 and len(adjusted) >= 2 and \\''',
     "tests/adaptive/test_routing_v2.py::test_exploration_promotes_only_rule_matches_and_is_deterministic"),

    ("M-11", "src/research_engine/adaptive/outcomes.py",
     '''    ev_component = _W_EVIDENCE * math.log1p(ev_weighted)''',
     '''    ev_component = _W_EVIDENCE * ev_weighted''',
     "tests/adaptive/test_outcomes.py::test_gain_v2_importance_weighting_not_gamed"),

    ("M-12", "src/research_engine/adaptive/outcomes.py",
     '''        and g.resolved_by_query_ids]''',
     '''        or True]''',
     "tests/adaptive/test_outcomes.py::test_gap_rename_earns_nothing"),

    ("M-13", "src/research_engine/adaptive/policies.py",
     '''            for k, cap in base.items():
                if k in cons and cons[k] > cap:''',
     '''            for k, cap in base.items():
                if False and k in cons and cons[k] > cap:''',
     "tests/policy/test_policy_registry.py::test_activation_refuses_out_of_bounds_bodies"),
]


def _run(cmd: list[str]) -> int:
    return subprocess.call(cmd, cwd=ROOT)


def main(selected: list[str]) -> int:
    results = []
    for mid, rel, old, new, tests in MUTATIONS:
        if selected and mid not in selected:
            continue
        target = ROOT / rel
        original = target.read_text()
        if old not in original:
            results.append((mid, "STALE-MUTATION (anchor missing)", False))
            continue
        tmpdir = tempfile.mkdtemp()
        backup = Path(tmpdir) / target.name
        shutil.copy(target, backup)
        try:
            target.write_text(original.replace(old, new, 1))
            rc = _run([str(ROOT / ".venv" / "bin" / "python"), "-m",
                       "pytest", "-x", "-q", tests])
            detected = rc != 0
            results.append((mid, f"tests {'DETECTED' if detected else 'SURVIVED'}",
                            detected))
        finally:
            shutil.copy(backup, target)
            shutil.rmtree(tmpdir, ignore_errors=True)

    print("\n=== MUTATION RESULTS ===")
    all_ok = True
    for mid, msg, ok in results:
        print(f"{mid}: {msg}")
        all_ok &= ok
    # safety: confirm working tree clean of mutations
    for _, rel, old, _, _ in MUTATIONS:
        t = ROOT / rel
        if old not in t.read_text() and old.strip():
            print(f"WARNING: verify revert of {rel}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# Phase 7 mutations (§38)
# M-14: dataset eligibility excludes synthetic (should be detected by eligibility filter)
# M-15: dataset fingerprint mutation breaks lineage (should break snapshot retrieval)
# M-16: future observation leaks into training (leakage detection must catch)
# M-17: candidate promotion without authorization (SafetyGate must block)
# M-18: frozen learner promotes (freeze_states block must fail)
# M-19: synthetic observation added to production dataset increases confidence (filter excludes)
# M-20: rollback target missing (activation must fail)
# M-21: dataset snapshot mutated after creation (fingerprint mismatch detects)
# M-22: evaluation on same data as training (independent split check detects)
# Note: mutation detectors verify invariants; exact mutation code depends on test harness.
