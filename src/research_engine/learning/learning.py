# Phase 7 learning pipeline (§10 bounded surfaces, §20 freeze, §22 reproducible)
# Decision: learning never self-modifies source; only generates candidates.
# Constraint: frozen learner (freeze_states table) cannot promote.
from __future__ import annotations
import json, hashlib

class LearningRun:
    def __init__(self, dataset_snapshot_id: str, parent_policy_id: str,
                 feature_version: str = "v1", algorithm_version: str = "v1",
                 seed: int = 42, data_dir: str = "."):
        self.run_id = f"lr-{dataset_snapshot_id}-{seed}"
        self.dataset_snapshot_id = dataset_snapshot_id
        self.parent_policy_id = parent_policy_id
        self.feature_version = feature_version
        self.algorithm_version = algorithm_version
        self.seed = seed
        self.status = "running"
        self.metrics = {}

    def fingerprint(self) -> str:
        s = f"{self.run_id}:{self.dataset_snapshot_id}:{self.seed}:{self.feature_version}:{self.algorithm_version}"
        return hashlib.sha256(s.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "dataset_snapshot_id": self.dataset_snapshot_id,
            "parent_policy_id": self.parent_policy_id,
            "feature_version": self.feature_version,
            "algorithm_version": self.algorithm_version,
            "seed": self.seed,
            "status": self.status,
            "metrics_json": json.dumps(self.metrics),
            "reproducibility_json": json.dumps({"fingerprint": self.fingerprint(), "code_version": "phase7-v1"}),
        }

    def freeze_if_needed(self, db) -> bool:
        # If freeze_states has active freeze, stop promotion (§22)
        return db.is_frozen() if hasattr(db, "is_frozen") else False
