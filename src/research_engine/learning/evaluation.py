# Phase 7 evaluation (§9 separation, §25 baseline beat, §26 multi-obj, §27 cost)
# Decision: independent holdout; never evaluate on training observations.
# Constraint: missing evidence never interpreted as positive (§25/§36).
from __future__ import annotations

def evaluate_candidate(candidate_dict: dict, train_obs: list, eval_obs: list) -> dict:
    # Minimal independent evaluation protocol (§9)
    # In production this would compute quality, unnecessary_calls, critic_recall, budget,
    # but here we verify structural separation and return metrics.
    metrics = {
        "train_count": len(train_obs),
        "eval_count": len(eval_obs),
        "independent": len(eval_obs) > 0 and len(train_obs) > 0,
        "baseline_beaten": False,  # must be set by external comparison
        "regressions": [],
        "quality_gain_estimate": 0.0,
        "cost_per_unit_quality": None,
    }
    # Basic leakage check (§8): ensure no shared fingerprints across splits
    train_fps = {o.get("fingerprint") for o in train_obs}
    eval_fps = {o.get("fingerprint") for o in eval_obs}
    overlap = train_fps & eval_fps
    if overlap:
        metrics["leakage_detected"] = True
        metrics["leakage_fingerprints"] = len(overlap)
    else:
        metrics["leakage_detected"] = False
    return metrics
