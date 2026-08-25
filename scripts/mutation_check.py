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
