"""Versioned policy registry (Phase 6 §52-§55, §63).

The system PROPOSES; humans ACTIVATE. There is deliberately NO code path
anywhere that deploys a learned policy automatically:

    draft ──(offline eval recorded)──► canary ──(explicit activate)──► active
       ▲                                                                  │
       └────────────── rollback == activate previous version ◄────────────┘

Baseline policies ship ACTIVE because they ARE the shipped deterministic
behavior (routing v1 rules, no exploration) — activating them is not an
adaptation decision. Everything learned starts as draft and stops until a
human moves it.
"""
from __future__ import annotations

from research_engine.storage.platform_db import PlatformDB

POLICY_ROUTING = "routing"
POLICY_QUERY = "query_strategy"
POLICY_MODEL = "model_routing"
POLICY_DEPTH = "research_depth"

# Routing baseline = Phase 5 hybrid rules, no learned adjustment, no
# exploration. Bounds here are HARD caps: no activated policy may exceed
# them (spec §60/§61 — learning operates beneath architectural invariants).
BASELINE_ROUTING = {
    "policy_id": POLICY_ROUTING,
    "version": "baseline",
    "features": ["domain_signals"],
    "weights": {},
    "constraints": {
        "max_adjustment": 0.15,      # |score delta| clamp vs rule score
        "min_runs_to_learn": 5,      # §10: never overfit handfuls
        "reliability_floor": 0.5,    # below this a specialist is unrouteable
        "max_specialists": 5,
    },
    "exploration": {"epsilon_standard": 0.0, "epsilon_low_stakes": 0.0},
    "evaluation_metrics": ["routing_accuracy", "unnecessary_calls"],
}

BASELINE_QUERY = {
    "policy_id": POLICY_QUERY,
    "version": "baseline",
    # Deterministic strategy rules stay authoritative; history may only
    # break ties in the low-stakes 'coverage adequate' branch (§19).
    "mode": "tie_break_only",
    "min_samples": 20,
    "family_boosts": {},
}


class PolicyError(ValueError):
    pass


class PolicyRegistry:
    """Human-controlled lifecycle over the platform policy table."""

    def __init__(self, db: PlatformDB):
        self.db = db

    # -- proposal / evaluation -------------------------------------------
    def propose(self, kind: str, version: str, body: dict,
                evaluation: dict | None = None,
                status: str = "draft") -> None:
        if version == "baseline":
            raise PolicyError("the shipped baseline is immutable; propose "
                              f"a new version instead of {kind}@baseline")
        self.db.save_policy(kind, version, body, status=status,
                            evaluation=evaluation)

    def record_evaluation(self, kind: str, version: str,
                          evaluation: dict,
                          promote_to_canary: bool = False) -> None:
        pol = self.db.get_policy(kind, version)
        if pol is None:
            raise PolicyError(f"unknown policy {kind}@{version}")
        merged = {**pol["evaluation"], **evaluation}
        self.db.save_policy(kind, version, pol["body"],
                            status="canary" if promote_to_canary else pol["status"],
                            evaluation=merged)

    # -- activation / rollback --------------------------------------------
    def activate(self, kind: str, version: str, reason: str = "") -> None:
        pol = self.db.get_policy(kind, version)
        if pol is None:
            raise PolicyError(f"unknown policy {kind}@{version}")
        body = pol.get("body") or {}
        if kind == POLICY_ROUTING:
            cons = (body.get("constraints") or {})
            base = BASELINE_ROUTING["constraints"]
            for k, cap in base.items():
                if k in cons and cons[k] > cap:
                    raise PolicyError(
                        f"{kind}@{version} violates hard bound {k}"
                        f"={cons[k]} > {cap}")
            eps = (body.get("exploration") or {})
            if float(eps.get("epsilon_standard", 0)) > 0.15 or \
                    float(eps.get("epsilon_low_stakes", 0)) > 0.15:
                raise PolicyError(f"{kind}@{version}: exploration epsilon "
                                  "> 0.15 refused")
        self.db.activate_policy(kind, version, reason=reason)

    def rollback(self, kind: str, reason: str = "") -> str | None:
        """Activate the most recently retired version of `kind`, if any."""
        retired = [p for p in self.db.list_policies(kind)
                   if p["status"] == "retired"]
        if not retired:
            return None
        retired.sort(key=lambda p: p.get("activated_at") or "", reverse=True)
        target = retired[0]["version"]
        self.activate(kind, target, reason=reason or "rollback")
        return target

    def deactivate(self, kind: str, reason: str = "") -> bool:
        """Return to shipped-baseline behavior."""
        active = self.db.active_policy(kind)
        if active is None:
            return False
        if active["version"] != "baseline":
            self.db.save_policy(active["kind"], active["version"],
                                active["body"], status="retired",
                                evaluation=active["evaluation"])
        if self.db.get_policy(kind, "baseline") is None:
            default = {
                POLICY_ROUTING: BASELINE_ROUTING,
                POLICY_QUERY: BASELINE_QUERY,
            }.get(kind)
            if default is None:
                return False
            self.db.save_policy(kind, "baseline", default, status="active",
                                evaluation={"seeded": True})
            return True
        self.db.activate_policy(kind, "baseline",
                                reason=reason or "deactivate to baseline")
        return True

    # -- reads --------------------------------------------------------------
    def active_body(self, kind: str) -> dict:
        pol = self.db.active_policy(kind)
        return pol["body"] if pol else {}

    def active_version(self, kind: str) -> str:
        pol = self.db.active_policy(kind)
        return pol["version"] if pol else ""

    def compare(self, kind: str, va: str, vb: str) -> dict:
        a, b = self.db.get_policy(kind, va), self.db.get_policy(kind, vb)
        if a is None or b is None:
            raise PolicyError("compare requires two existing versions")
        diff: dict = {}
        keys = set(a["body"]) | set(b["body"])
        for k in sorted(keys):
            av, bv = a["body"].get(k), b["body"].get(k)
            if av != bv:
                diff[k] = {"A": av, "B": bv}
        return {
            "kind": kind, "A": {"version": va, "evaluation": a["evaluation"]},
            "B": {"version": vb, "evaluation": b["evaluation"]},
            "body_diff": diff,
        }

    def list(self, kind: str = "") -> list[dict]:
        return self.db.list_policies(kind)


def ensure_baseline_policies(db: PlatformDB) -> None:
    """Idempotent seed: baselines describe SHIPPED behavior, hence active."""
    defaults = {
        POLICY_ROUTING: BASELINE_ROUTING,
        POLICY_QUERY: BASELINE_QUERY,
    }
    for kind, body in defaults.items():
        if db.get_policy(kind, body["version"]) is None:
            db.save_policy(kind, body["version"], body, status="active",
                           evaluation={"seeded": True})
