"""INV-036: honest idea evaluation (startup_validation engine)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from research_engine.specialists.startup.idea import build_idea_question

_SPEC = Path(__file__).resolve().parents[1] / "specialists" / "test_startup_validation.py"
_mod_spec = importlib.util.spec_from_file_location("_startup_validation_fixtures", _SPEC)
fx = importlib.util.module_from_spec(_mod_spec)
sys.modules["_startup_validation_fixtures"] = fx
_mod_spec.loader.exec_module(fx)


def test_inv_036_positive_verdict_needs_counterevidence_and_competition(tmp_path):
    orch, cfg = fx._project(tmp_path, build_idea_question(fx.IDEA, **fx.CARD_FIELDS))
    out = fx._svc(cfg, tmp_path).run_validation_pipeline(orch.project.id)
    ev = out["evaluation"]
    checks = ev["gate"]["checks"]
    if not (checks["counterevidence_searched"] and checks["competition_researched"]):
        assert not ev["verdict"]["positive"]


def test_inv_036_traction_and_answers_never_become_evidence(tmp_path):
    q = build_idea_question(fx.IDEA, existing_traction="500 people on the waitlist and 20 paying",
                            **fx.CARD_FIELDS)
    orch, cfg = fx._project(tmp_path, q)
    pid = orch.project.id
    before = len(orch.repos.evidence.all(pid))
    fx._svc(cfg, tmp_path).run_validation_pipeline(pid)
    assert len(orch.repos.evidence.all(pid)) == before
    assert not any("waitlist" in e.claim_text for e in orch.repos.evidence.all(pid))


def test_inv_036_unlinked_market_evidence_is_never_padded_onto_the_idea(tmp_path):
    unrelated = [("https://x.example.com/a", "Quantum error correction thresholds improved "
                  "with surface codes in superconducting qubits", 2)]
    q = build_idea_question("Subscription crate for pet iguana owners",
                            problem="iguana owners cannot find fresh reptile food",
                            customer_segment="pet iguana owners")
    orch, cfg = fx._project(tmp_path, q, evidence=unrelated)
    out = fx._svc(cfg, tmp_path).run_validation_pipeline(orch.project.id)
    assert out["evaluation"]["linked_evidence"] == 0
    assert out["evaluation"]["verdict"]["verdict"] == "NOT_ENOUGH_EVIDENCE"
