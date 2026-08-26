# Phase 7 production-learning persistence.
# Decision: separate module from PlatformDB to avoid corrupting existing
# adaptive/policy persistence; shares platform.sqlite via same path convention.
# Constraint: tables never authorize promotion; activation requires external
# authorization (INV-017) and rollback target must be confirmed.

import sqlite3, json, os
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS production_observations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL DEFAULT '',
    task_id TEXT NOT NULL DEFAULT '',
    observation_time TEXT NOT NULL,
    provenance_type TEXT NOT NULL DEFAULT 'real',
    model_family TEXT DEFAULT '',
    specialist TEXT DEFAULT '',
    routing_version TEXT DEFAULT '',
    policy_version TEXT DEFAULT '',
    outcome_quality REAL DEFAULT 0.0,
    critic_result TEXT DEFAULT '',
    budget_spent REAL DEFAULT 0.0,
    latency_ms REAL DEFAULT 0.0,
    observation_json TEXT NOT NULL DEFAULT '{}',
    fingerprint TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs_fp ON production_observations(fingerprint);

CREATE TABLE IF NOT EXISTS dataset_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    creation_ts TEXT NOT NULL,
    observation_range_start TEXT DEFAULT '',
    observation_range_end TEXT DEFAULT '',
    eligible_count INTEGER DEFAULT 0,
    excluded_count INTEGER DEFAULT 0,
    eligibility_criteria_json TEXT DEFAULT '{}',
    source_distribution_json TEXT DEFAULT '{}',
    task_distribution_json TEXT DEFAULT '{}',
    split_version TEXT DEFAULT '',
    seed INTEGER DEFAULT 0,
    schema_version TEXT DEFAULT '',
    parent_snapshot_id TEXT DEFAULT '',
    created_by TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_snap_fp ON dataset_snapshots(fingerprint);

CREATE TABLE IF NOT EXISTS learning_runs (
    run_id TEXT PRIMARY KEY,
    dataset_snapshot_id TEXT DEFAULT '',
    parent_policy_id TEXT DEFAULT '',
    feature_version TEXT DEFAULT '',
    algorithm_version TEXT DEFAULT '',
    seed INTEGER DEFAULT 0,
    duration_s REAL DEFAULT 0.0,
    observations_used INTEGER DEFAULT 0,
    observations_excluded INTEGER DEFAULT 0,
    metrics_json TEXT DEFAULT '{}',
    reproducibility_json TEXT DEFAULT '{}',
    status TEXT DEFAULT 'running',
    created_at TEXT NOT NULL,
    completed_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_run_dataset ON learning_runs(dataset_snapshot_id);

CREATE TABLE IF NOT EXISTS candidate_policies (
    candidate_id TEXT PRIMARY KEY,
    parent_policy_id TEXT DEFAULT '',
    generation_method TEXT DEFAULT '',
    dataset_snapshot_id TEXT DEFAULT '',
    learning_run_id TEXT DEFAULT '',
    expected_gain REAL DEFAULT 0.0,
    evaluation_metrics_json TEXT DEFAULT '{}',
    regression_metrics_json TEXT DEFAULT '{}',
    safety_status TEXT DEFAULT 'observed',
    confidence REAL DEFAULT 0.0,
    uncertainty_json TEXT DEFAULT '{}',
    creation_ts TEXT NOT NULL,
    evaluation_ts TEXT DEFAULT '',
    review_ts TEXT DEFAULT '',
    canary_ts TEXT DEFAULT '',
    activation_ts TEXT DEFAULT '',
    rollback_target_policy_id TEXT DEFAULT '',
    feature_version TEXT DEFAULT '',
    code_version TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_cand_parent ON candidate_policies(parent_policy_id);
CREATE INDEX IF NOT EXISTS idx_cand_safety ON candidate_policies(safety_status);

CREATE TABLE IF NOT EXISTS canary_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT DEFAULT '',
    measurement_start TEXT DEFAULT '',
    measurement_end TEXT DEFAULT '',
    quality_score REAL DEFAULT 0.0,
    routing_accuracy REAL DEFAULT 0.0,
    unnecessary_calls INTEGER DEFAULT 0,
    latency_ms REAL DEFAULT 0.0,
    failure_rate REAL DEFAULT 0.0,
    budget_spent REAL DEFAULT 0.0,
    specialist_utilization_json TEXT DEFAULT '{}',
    regression_flags_json TEXT DEFAULT '{}',
    drift_state_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_canary_cand ON canary_metrics(candidate_id);

CREATE TABLE IF NOT EXISTS policy_activations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT DEFAULT '',
    previous_active_policy_id TEXT DEFAULT '',
    activated_by TEXT DEFAULT '',
    authorization_reference TEXT DEFAULT '',
    activation_ts TEXT NOT NULL,
    rollback_target_confirmed INTEGER DEFAULT 0,
    approved_by TEXT DEFAULT '',
    approved_at TEXT DEFAULT '',
    canary_metrics_id INTEGER DEFAULT 0,
    audit_json TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_act_cand ON policy_activations(candidate_id);

CREATE TABLE IF NOT EXISTS freeze_states (
    freeze_id INTEGER PRIMARY KEY AUTOINCREMENT,
    reason TEXT DEFAULT '',
    frozen_at TEXT NOT NULL,
    resumed_at TEXT DEFAULT '',
    affected_candidates_json TEXT DEFAULT '{}',
    dataset_corruption_flag INTEGER DEFAULT 0,
    telemetry_failure_flag INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
"""

class LearningDB:
    def __init__(self, data_dir: str | os.PathLike = "."):
        self.path = Path(data_dir) / "platform.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.path), timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            conn.executescript(_SCHEMA)
            conn.commit()

    def _conn(self):
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def save_observation(self, obs: dict) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO production_observations
                (id, project_id, task_id, observation_time, provenance_type,
                 model_family, specialist, routing_version, policy_version,
                 outcome_quality, critic_result, budget_spent, latency_ms,
                 observation_json, fingerprint, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                obs.get("id"), obs.get("project_id"), obs.get("task_id"),
                obs.get("observation_time"), obs.get("provenance_type", "real"),
                obs.get("model_family"), obs.get("specialist"),
                obs.get("routing_version"), obs.get("policy_version"),
                obs.get("outcome_quality", 0.0), obs.get("critic_result", ""),
                obs.get("budget_spent", 0.0), obs.get("latency_ms", 0.0),
                json.dumps(obs.get("observation_json", {})),
                obs.get("fingerprint", ""), obs.get("created_at"),
            ))
            conn.commit()

    def get_observations_by_fingerprint(self, fingerprint: str = "") -> list[dict]:
        with self._conn() as conn:
            if fingerprint:
                cur = conn.execute("SELECT * FROM production_observations WHERE fingerprint = ? ORDER BY observation_time DESC", (fingerprint,))
            else:
                cur = conn.execute("SELECT * FROM production_observations ORDER BY observation_time DESC LIMIT 1000")
            return [dict(r) for r in cur.fetchall()]

    def save_dataset_snapshot(self, snap: dict) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO dataset_snapshots
                (snapshot_id, fingerprint, creation_ts, observation_range_start,
                 observation_range_end, eligible_count, excluded_count,
                 eligibility_criteria_json, source_distribution_json,
                 task_distribution_json, split_version, seed, schema_version,
                 parent_snapshot_id, created_by, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snap.get("snapshot_id"), snap.get("fingerprint"),
                snap.get("creation_ts"), snap.get("observation_range_start"),
                snap.get("observation_range_end"), snap.get("eligible_count", 0),
                snap.get("excluded_count", 0),
                json.dumps(snap.get("eligibility_criteria_json", {})),
                json.dumps(snap.get("source_distribution_json", {})),
                json.dumps(snap.get("task_distribution_json", {})),
                snap.get("split_version"), snap.get("seed", 0),
                snap.get("schema_version"), snap.get("parent_snapshot_id"),
                snap.get("created_by"), json.dumps(snap.get("metadata_json", {})),
            ))
            conn.commit()

    def get_dataset_snapshot(self, snapshot_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM dataset_snapshots WHERE snapshot_id = ?", (snapshot_id,)).fetchone()
            return dict(row) if row else None

    def get_snapshot_by_fingerprint(self, fingerprint: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM dataset_snapshots WHERE fingerprint = ?", (fingerprint,)).fetchone()
            return dict(row) if row else None

    def save_learning_run(self, run: dict) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO learning_runs
                (run_id, dataset_snapshot_id, parent_policy_id, feature_version,
                 algorithm_version, seed, duration_s, observations_used,
                 observations_excluded, metrics_json, reproducibility_json,
                 status, created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run.get("run_id"), run.get("dataset_snapshot_id"),
                run.get("parent_policy_id"), run.get("feature_version"),
                run.get("algorithm_version"), run.get("seed", 0),
                run.get("duration_s", 0.0), run.get("observations_used", 0),
                run.get("observations_excluded", 0),
                json.dumps(run.get("metrics_json", {})),
                json.dumps(run.get("reproducibility_json", {})),
                run.get("status", "running"), run.get("created_at"),
                run.get("completed_at", ""),
            ))
            conn.commit()

    def get_learning_run(self, run_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM learning_runs WHERE run_id = ?", (run_id,)).fetchone()
            return dict(row) if row else None

    def save_candidate_policy(self, cand: dict) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO candidate_policies
                (candidate_id, parent_policy_id, generation_method,
                 dataset_snapshot_id, learning_run_id, expected_gain,
                 evaluation_metrics_json, regression_metrics_json,
                 safety_status, confidence, uncertainty_json,
                 creation_ts, evaluation_ts, review_ts, canary_ts,
                 activation_ts, rollback_target_policy_id, feature_version,
                 code_version, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cand.get("candidate_id"), cand.get("parent_policy_id"),
                cand.get("generation_method"), cand.get("dataset_snapshot_id"),
                cand.get("learning_run_id"), cand.get("expected_gain", 0.0),
                json.dumps(cand.get("evaluation_metrics_json", {})),
                json.dumps(cand.get("regression_metrics_json", {})),
                cand.get("safety_status", "observed"), cand.get("confidence", 0.0),
                json.dumps(cand.get("uncertainty_json", {})),
                cand.get("creation_ts"), cand.get("evaluation_ts", ""),
                cand.get("review_ts", ""), cand.get("canary_ts", ""),
                cand.get("activation_ts", ""), cand.get("rollback_target_policy_id"),
                cand.get("feature_version"), cand.get("code_version"),
                json.dumps(cand.get("metadata_json", {})),
            ))
            conn.commit()

    def get_candidate_policy(self, candidate_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM candidate_policies WHERE candidate_id = ?", (candidate_id,)).fetchone()
            return dict(row) if row else None

    def update_candidate_status(self, candidate_id: str, status: str, ts: str = "") -> None:
        with self._conn() as conn:
            conn.execute("UPDATE candidate_policies SET safety_status = ?, evaluation_ts = ? WHERE candidate_id = ?", (status, ts or "", candidate_id))
            conn.commit()

    def save_canary_metrics(self, cm: dict) -> int:
        with self._conn() as conn:
            cur = conn.execute("""
                INSERT INTO canary_metrics
                (candidate_id, measurement_start, measurement_end, quality_score,
                 routing_accuracy, unnecessary_calls, latency_ms, failure_rate,
                 budget_spent, specialist_utilization_json, regression_flags_json,
                 drift_state_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cm.get("candidate_id"), cm.get("measurement_start"),
                cm.get("measurement_end"), cm.get("quality_score", 0.0),
                cm.get("routing_accuracy", 0.0), cm.get("unnecessary_calls", 0),
                cm.get("latency_ms", 0.0), cm.get("failure_rate", 0.0),
                cm.get("budget_spent", 0.0),
                json.dumps(cm.get("specialist_utilization_json", {})),
                json.dumps(cm.get("regression_flags_json", {})),
                json.dumps(cm.get("drift_state_json", {})),
                cm.get("created_at"),
            ))
            conn.commit()
            return cur.lastrowid

    def get_canary_for_candidate(self, candidate_id: str) -> list[dict]:
        with self._conn() as conn:
            cur = conn.execute("SELECT * FROM canary_metrics WHERE candidate_id = ? ORDER BY created_at DESC", (candidate_id,))
            return [dict(r) for r in cur.fetchall()]

    def save_policy_activation(self, act: dict) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO policy_activations
                (candidate_id, previous_active_policy_id, activated_by,
                 authorization_reference, activation_ts, rollback_target_confirmed,
                 approved_by, approved_at, canary_metrics_id, audit_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                act.get("candidate_id"), act.get("previous_active_policy_id"),
                act.get("activated_by"), act.get("authorization_reference"),
                act.get("activation_ts"), act.get("rollback_target_confirmed", 0),
                act.get("approved_by"), act.get("approved_at"),
                act.get("canary_metrics_id", 0),
                json.dumps(act.get("audit_json", {})),
            ))
            conn.commit()

    def get_activations(self, limit: int = 10) -> list[dict]:
        with self._conn() as conn:
            cur = conn.execute("SELECT * FROM policy_activations ORDER BY activation_ts DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]

    def save_freeze_state(self, freeze: dict) -> int:
        with self._conn() as conn:
            cur = conn.execute("""
                INSERT INTO freeze_states
                (reason, frozen_at, resumed_at, affected_candidates_json,
                 dataset_corruption_flag, telemetry_failure_flag, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                freeze.get("reason"), freeze.get("frozen_at"),
                freeze.get("resumed_at", ""),
                json.dumps(freeze.get("affected_candidates_json", {})),
                freeze.get("dataset_corruption_flag", 0),
                freeze.get("telemetry_failure_flag", 0),
                freeze.get("created_at"),
            ))
            conn.commit()
            return cur.lastrowid

    def is_frozen(self) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM freeze_states WHERE resumed_at = '' ORDER BY frozen_at DESC LIMIT 1").fetchone()
            return row is not None

    def get_latest_freeze(self) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM freeze_states ORDER BY frozen_at DESC LIMIT 1").fetchone()
            return dict(row) if row else None
