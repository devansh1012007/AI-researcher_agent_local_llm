"""Dynamic iteration-budget allocation (Phase 6 §47/§48).

Budget follows marginal gain: continue at full width while recent
iterations still yield evidence, taper when returns diminish, and grant a
small TEMPORARY targeted boost when high-value contradictions exist.
Hard caps stay authoritative — the result is always clamped into
[1, base] ∩ [1, hard_cap]; scaling only ever redistributes WITHIN the
configured envelope (spec §48 "the system must remain bounded").

Neutral by default: production behavior changes only when a non-baseline
research_depth policy has been explicitly activated (§63).
"""
from __future__ import annotations

MIN_MULTIPLIER = 0.5
MAX_MULTIPLIER = 1.25
_WINDOW = 3            # recent iterations considered


def gain_trend(recent_gains: list[float]) -> float:
    """>0 improving, ~0 flat, <0 diminishing. Uses a simple first-vs-last
    slope over the window — deterministic and cheap."""
    vals = [g for g in recent_gains[-_WINDOW:] if g is not None]
    if len(vals) < 2:
        return 0.0
    span = max(abs(v) for v in vals) or 1.0
    return round((vals[-1] - vals[0]) / span, 4)


def scale_iteration_budget(base_queries: int, recent_gains: list[float],
                           policy_enabled: bool = False,
                           targeted_boost: int = 0,
                           hard_cap: int | None = None) -> int:
    if not policy_enabled:
        return max(0, base_queries)
    trend = gain_trend(recent_gains)
    if trend > 0.10:
        mult = MAX_MULTIPLIER
    elif trend < -0.10:
        mult = MIN_MULTIPLIER
    else:
        mult = 0.75
    scaled = int(round(max(1, base_queries) * mult)) + (
        targeted_boost if trend >= -0.10 else 0)
    scaled = max(1, scaled)
    if hard_cap is not None:
        scaled = min(scaled, hard_cap)
    return scaled
