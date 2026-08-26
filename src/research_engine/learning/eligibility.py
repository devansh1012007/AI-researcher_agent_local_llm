# Phase 7 dataset eligibility (§5/§8/§9/§32/§33/§19)
# Decision: eligibility is explicit (not automatic); synthetic observations
# (benchmark/replayed/synthetic) are labeled and never enter production
# training confidence (§19/§33).
# Constraint: temporal leakage prevented by observation_time range checks.

from __future__ import annotations
import json

ELIGIBILITY_CRITERIA = {
    "min_observations": 5,
    "require_critic": False,
    "allow_synthetic": False,
    "max_age_days": 90,
    "require_provenance": True,
    "exclude_duplicate_fingerprints": True,
    "exclude_future_observations": True,
}

class EligibilityFilter:
    def __init__(self, criteria: dict | None = None):
        self.criteria = {**ELIGIBILITY_CRITERIA, **(criteria or {})}

    def is_eligible(self, obs: dict, reference_time: str = "") -> bool:
        # Provenance: synthetic must not increase production confidence (§19)
        prov = obs.get("provenance_type", "real")
        if not self.criteria.get("allow_synthetic") and prov in ("synthetic", "benchmark", "replayed"):
            return False
        # Temporal leakage (§8): observation must not be in future relative to decision
        if self.criteria.get("exclude_future_observations") and reference_time:
            if obs.get("observation_time", "") > reference_time:
                return False
        # Data completeness
        if not obs.get("id") or not obs.get("fingerprint"):
            return False
        return True

    def filter_observations(self, observations: list[dict], reference_time: str = "") -> tuple[list[dict], dict]:
        eligible = []
        excluded = {"synthetic": 0, "incomplete": 0, "future": 0, "duplicate": 0}
        seen_fp = set()
        for obs in observations:
            fp = obs.get("fingerprint", "")
            if self.criteria.get("exclude_duplicate_fingerprints") and fp in seen_fp:
                excluded["duplicate"] += 1
                continue
            if fp:
                seen_fp.add(fp)
            if not self.is_eligible(obs, reference_time):
                prov = obs.get("provenance_type", "real")
                if prov in ("synthetic", "benchmark", "replayed"):
                    excluded["synthetic"] += 1
                elif obs.get("observation_time", "") > reference_time:
                    excluded["future"] += 1
                else:
                    excluded["incomplete"] += 1
                continue
            eligible.append(obs)
        return eligible, excluded
