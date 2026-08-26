"""§96: routing suite — canonical tests live in
tests/adaptive/test_routing_v2.py (shared conftest). This module re-exports
them so `pytest tests/routing` runs the same coverage."""
from tests.adaptive.test_routing_v2 import (  # noqa: F401
    test_cold_start_identical_to_v1,
    test_decision_record_persisted_with_why,
    test_exploration_promotes_only_rule_matches_and_is_deterministic,
    test_history_adjusts_within_clamp_only_on_ties,
    test_min_samples_gate_prevents_overfit,
)
