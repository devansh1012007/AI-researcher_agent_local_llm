# Phase 7 safety / freeze / rollback / authorization (§17-23, 35, 36, 45, 46)
# Decision: human approval always required; no autonomous path exists.
# Constraint: frozen learner cannot promote; missing evidence = no promotion.
from __future__ import annotations

class SafetyGate:
    def __init__(self, db):
        self.db = db

    def is_frozen(self) -> bool:
        return self.db.is_frozen() if hasattr(self.db, "is_frozen") else False

    def can_promote(self, candidate_id: str, authorization_ref: str = "") -> bool:
        # Must have authorization reference (§45); frozen state blocks (§22);
        # rollback target must be known (§19); missing evidence blocks (§36)
        if not authorization_ref:
            return False
        if self.is_frozen():
            return False
        cand = self.db.get_candidate_policy(candidate_id) if hasattr(self.db, "get_candidate_policy") else None
        if not cand:
            return False
        if cand.get("safety_status") not in ("evaluated", "canary", "approved"):
            return False
        # Rollback target must exist
        rollback_target = cand.get("rollback_target_policy_id")
        if not rollback_target:
            return False
        return True

    def can_activate(self, candidate_id: str, authorization_ref: str = "") -> bool:
        # Activation requires explicit external approval (§17/§45)
        if not authorization_ref:
            return False
        return self.can_promote(candidate_id, authorization_ref)
