# Phase 7 candidate lifecycle (§12)
# Decision: candidate must have parent_policy_id, dataset_snapshot_id,
# evaluation_metrics_json, regression_metrics_json, safety_status.
# Constraint: never activated without external authorization (INV-017).
from __future__ import annotations
import json

class CandidatePolicy:
    STATES = ["observed", "learned", "evaluated", "review_required", "canary", "approved", "rejected", "active", "retired"]

    def __init__(self, candidate_id: str, parent_policy_id: str,
                 generation_method: str = "learning", dataset_snapshot_id: str = "",
                 learning_run_id: str = "", expected_gain: float = 0.0,
                 evaluation_metrics_json: dict | None = None,
                 regression_metrics_json: dict | None = None,
                 feature_version: str = "v1", code_version: str = "v1"):
        self.candidate_id = candidate_id
        self.parent_policy_id = parent_policy_id
        self.generation_method = generation_method
        self.dataset_snapshot_id = dataset_snapshot_id
        self.learning_run_id = learning_run_id
        self.expected_gain = expected_gain
        self.evaluation_metrics_json = evaluation_metrics_json or {}
        self.regression_metrics_json = regression_metrics_json or {}
        self.safety_status = "observed"
        self.confidence = 0.0
        self.feature_version = feature_version
        self.code_version = code_version
        self.creation_ts = ""

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "parent_policy_id": self.parent_policy_id,
            "generation_method": self.generation_method,
            "dataset_snapshot_id": self.dataset_snapshot_id,
            "learning_run_id": self.learning_run_id,
            "expected_gain": self.expected_gain,
            "evaluation_metrics_json": json.dumps(self.evaluation_metrics_json),
            "regression_metrics_json": json.dumps(self.regression_metrics_json),
            "safety_status": self.safety_status,
            "confidence": self.confidence,
            "feature_version": self.feature_version,
            "code_version": self.code_version,
            "creation_ts": self.creation_ts,
        }

    def can_activate(self, db) -> bool:
        # Must have evaluation evidence, pass safety, have rollback target
        if self.safety_status not in ("approved", "canary"):
            return False
        # External authorization required (§45); this class never decides activation alone
        return False  # Explicit authorization must come from external gate
