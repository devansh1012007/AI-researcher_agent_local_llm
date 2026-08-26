"""Model routing analytics (Phase 6 §24-§27).

v1 is OBSERVE + ADVISE: selection stays config-driven; this module turns
llm_perf telemetry into per-model quality-per-resource ratios and detects
statistically conservative degradation signals. Nothing here silently swaps
a production model (§27) — it produces recommendations that surface in the
quality dashboard and policy proposals.
"""
from __future__ import annotations

MIN_CALLS_FOR_JUDGMENT = 10      # §10 anti-overfit analog for models
DEGRADED_FAILURE_RATE = 0.5
DEGRADED_SCHEMA_RATE = 0.5


def quality_per_second(row: dict) -> float:
    """Calls/sec is a throughput proxy; combined with failure rate it gives
    'useful calls per second' (§25)."""
    lat = row.get("avg_latency_s") or 0.0
    if lat <= 0:
        return 0.0
    ok_rate = 1.0 - _rate(row)
    return round(ok_rate / lat, 4)


def _rate(row: dict) -> float:
    calls = row.get("calls") or 0
    return (row.get("failures") or 0) / calls if calls else 0.0


def schema_reliability(row: dict) -> float:
    calls = row.get("calls") or 0
    if not calls:
        return 1.0
    return round(1.0 - (row.get("schema_failures") or 0) / calls, 4)


def assess_models(db, role: str = "") -> list[dict]:
    """Per (provider, model, role): health verdict + efficiency ratios."""
    out = []
    for r in db.list_llm_perf(role):
        calls = r["calls"] or 0
        verdict = "insufficient_data"
        rec = "observe"
        if calls >= MIN_CALLS_FOR_JUDGMENT:
            fail_r, sch_r = _rate(r), 1.0 - schema_reliability(r)
            if fail_r >= DEGRADED_FAILURE_RATE or \
                    sch_r >= DEGRADED_SCHEMA_RATE:
                verdict = "degraded"
                # §88: hold routing / fall back — recommendation only.
                rec = ("fallback" if fail_r >= DEGRADED_FAILURE_RATE
                       else "hold_and_investigate_schema")
            else:
                verdict = "healthy"
                rec = "keep"
        out.append({
            **r,
            "failure_rate": round(_rate(r), 4),
            "schema_reliability": schema_reliability(r),
            "quality_per_second": quality_per_second(r),
            "verdict": verdict,
            "recommendation": rec,
        })
    out.sort(key=lambda x: (-x["calls"], x["avg_latency_s"]))
    return out


def detect_degradation(db, role: str) -> dict | None:
    """First degraded model entry for a role, else None."""
    for entry in assess_models(db, role):
        if entry["verdict"] == "degraded":
            return entry
    return None
