"""Routing v2 (Phase 6 §11-§17, §56-§57): rules stay the floor; learned
history may only ADJUST rule scores within hard clamps, and exploration is
controlled, bounded, and explainable.

Safety properties (spec §60/§61):
- Cold start (no history) ⇒ bit-identical Phase 5 routing.
- Score adjustments are clamped to ±max_adjustment (policy constraint,
  hard-capped at 0.15 by the registry).
- Specialists below the reliability floor are never boosted.
- Exploration only ever PROMOTES an already-rule-matched specialist —
  it can never inject a specialist the deterministic rules rejected.
- Every decision is recorded with chosen/alternatives/reason/policy_version/
  expected_gain so "why X?" is always answerable (§56).
"""
from __future__ import annotations

import hashlib
import random

from research_engine.adaptive.policies import BASELINE_ROUTING
from research_engine.specialists.routing import Selection, route


def _seed(question: str) -> int:
    # Deterministic exploration: same question+state ⇒ same choice (§59).
    return int(hashlib.sha256((question or "").encode()).hexdigest()[:12], 16)


def specialist_stats(db, specialist_id: str, task_type: str,
                     min_runs: int) -> dict | None:
    """Context-conditioned stats (§10). Rows recorded under richer keys
    ('mode:bucket') also match their bare-mode prefix."""
    rows = [r for r in db.list_specialist_perf(specialist_id)
            if r["task_type"] == task_type
            or r["task_type"].startswith(f"{task_type}:")]
    if not rows:
        return None
    runs = sum(r["runs"] for r in rows)
    failures = sum(r["failures"] for r in rows)
    if runs < min_runs:
        return None     # not enough evidence to adjust anything (§10)
    avg_latency = (sum(r["avg_latency_s"] * r["runs"] for r in rows) / runs) \
        if runs else 0.0
    return {"runs": runs, "failure_rate": failures / runs,
            "avg_latency": avg_latency}


def route_v2(question: str, subquestions: list[str] | None = None,
             db=None, llm=None, max_specialists: int = 5,
             criticality: str = "STANDARD",
             policy_body: dict | None = None,
             project_id: str = "",
             task_features: dict | None = None):
    """Returns (selections, decision_record_dict).

    `db` is the platform store; when absent the call degenerates to exact
    Phase 5 behavior (used by tests and offline goldens).
    """
    base = route(question, subquestions, llm=llm,
                 max_specialists=max_specialists)
    policy = policy_body or BASELINE_ROUTING
    cons = {**BASELINE_ROUTING["constraints"], **(policy.get("constraints") or {})}
    expl_cfg = {**BASELINE_ROUTING["exploration"],
                **(policy.get("exploration") or {})}

    decision = {
        "kind": "select_specialist",
        "chosen": [s.specialist_id for s in base],
        "alternatives": [],
        "reason": "rules" if not base else
                  f"rules ({base[0].specialist_id} top)",
        "policy_version": str(policy.get("version", "baseline")),
        "features": task_features or {},
        "expected_gain": float(base[0].score) if base else 0.0,
    }
    if db is None or not base:
        return base, decision

    task_type = (task_features or {}).get("research_type", "") or "generic"
    adjusted = list(base)       # fresh Selection objects from route()
    alternatives: list[str] = []
    for sel in base:
        stats = specialist_stats(db, sel.specialist_id, task_type,
                                 int(cons["min_runs_to_learn"]))
        note = ""
        if stats is not None:
            rel = 1.0 - stats["failure_rate"]
            if rel >= float(cons["reliability_floor"]):
                # Linear trust term clamped to ±max_adjustment.
                adj = cons["max_adjustment"] * (2.0 * rel - 1.0)
                sel.score = round(sel.score + adj, 4)
                note = f"history adj {adj:+.2f} (rel {rel:.2f})"
                sel.annotations.append(note)
            else:
                note = (f"below reliability floor (rel {rel:.2f}) — "
                        "no boost")
                sel.annotations.append(note)
        alternatives.append(sel.specialist_id)

    adjusted.sort(key=lambda s: -s.score)

    # Controlled exploration (§13/§14): bounded by criticality — HIGH_RIGOR
    # NEVER explores; STANDARD uses its budget; lower stakes may use theirs.
    # Exploration only ever PROMOTES an already-rule-matched candidate.
    if criticality == "HIGH_RIGOR":
        eps = 0.0
    else:
        eps_key = ("epsilon_standard" if criticality == "STANDARD"
                   else "epsilon_low_stakes")
        eps = float(expl_cfg.get(eps_key, 0.0))
    explored = ""
    if eps > 0 and len(adjusted) >= 2 and \
            random.Random(_seed(question + task_type)).random() < eps:
        tail = adjusted.pop()          # least favored rule match
        tail.annotations.append("exploration")
        adjusted.insert(0, tail)
        explored = tail.specialist_id

    if explored:
        decision["reason"] = f"explore({explored}) within rule matches"
        decision["chosen"] = [explored] + [s.specialist_id for s in adjusted
                                           if s.specialist_id != explored]
    elif any(a.annotations for a in adjusted):
        decision["reason"] = "rules+bounded history adjustment"
    top = adjusted[0] if adjusted else None
    decision["alternatives"] = [a for a in alternatives
                                if not top or a != top.specialist_id]
    if top is not None:
        try:
            db.save_decision(
                f"dec_{_seed(question + str(len(alternatives))) % 10**10}",
                project_id=project_id, kind="select_specialist",
                chosen=top.specialist_id, alternatives=decision["alternatives"],
                reason=decision["reason"],
                policy_version=f"routing@{decision['policy_version']}",
                features=decision["features"],
                expected_gain=min(1.0, top.score / 5.0))
        except Exception:
            pass
    return adjusted[:max_specialists], decision
