"""Diversity & drift monitors (Phase 6 §71-§78).

Diagnostic ONLY: concentration flags prompt investigation; nothing here
forces usage quotas (§72). Drift is measured as behavior change between the
older and newer halves of recorded decisions/perf rows.
"""
from __future__ import annotations

from collections import Counter

CONCENTRATION_FLAG = 0.80     # single bucket share that warrants a look
MIN_DECISIONS_FOR_DRIFT = 10


def _share(counter: Counter) -> dict:
    total = sum(counter.values()) or 1
    return {k: round(v / total, 4) for k, v in counter.most_common()}


def diversity_report(db) -> dict:
    """Usage distribution across specialists, query families, sources,
    models (§71-§74)."""
    spec_counter: Counter = Counter()
    for r in db.list_specialist_perf():
        spec_counter[r["specialist"]] += r["runs"]
    fam_counter: Counter = Counter()
    for r in db.list_query_family_perf():
        fam_counter[r["family"]] += r["queries"]
    src_counter: Counter = Counter()
    for r in db.list_source_perf():
        src_counter[r["source_type"]] += r["sources"]
    model_counter: Counter = Counter()
    for r in db.list_llm_perf():
        model_counter[f"{r['provider']}/{r['model']}"] += r["calls"]

    def _flag(shares: dict) -> bool:
        return bool(shares) and next(iter(shares.values())) >= CONCENTRATION_FLAG

    spec_share = _share(spec_counter)
    fam_share = _share(fam_counter)
    src_share = _share(src_counter)
    model_share = _share(model_counter)
    return {
        "specialists": {"shares": spec_share,
                        "concentration_flag": _flag(spec_share)},
        "query_families": {"shares": fam_share,
                           "confirmation_loop_flag": _flag(fam_share)},
        "sources": {"shares": src_share,
                    "concentration_flag": _flag(src_share)},
        "models": {"shares": model_share,
                   "concentration_flag": _flag(model_share)},
    }


def policy_drift_report(db, kind: str = "select_specialist") -> dict:
    """Compare chosen-distribution between older/newer halves of decisions
    (§76). Large share shifts = drift worth investigating."""
    decisions = list(reversed(db.list_decisions(kind=kind, limit=500)))
    if len(decisions) < MIN_DECISIONS_FOR_DRIFT:
        return {"status": "insufficient_data",
                "decisions": len(decisions)}
    half = len(decisions) // 2
    old = _share(Counter(d["chosen"] or "(none)" for d in decisions[:half]))
    new = _share(Counter(d["chosen"] or "(none)" for d in decisions[half:]))
    shifts = {}
    keys = set(old) | set(new)
    for k in keys:
        delta = round(new.get(k, 0.0) - old.get(k, 0.0), 4)
        if abs(delta) >= 0.15:
            shifts[k] = delta
    expected_gain_old = [d.get("expected_gain") or 0 for d in decisions[:half]]
    expected_gain_new = [d.get("expected_gain") or 0 for d in decisions[half:]]
    return {
        "status": "ok",
        "decisions": len(decisions),
        "old_distribution": old,
        "new_distribution": new,
        "significant_shifts": shifts,
        "avg_expected_gain_change": round(
            (sum(expected_gain_new) / max(1, len(expected_gain_new)))
            - (sum(expected_gain_old) / max(1, len(expected_gain_old))), 4),
    }


def specialist_drift_report(db, specialist_id: str) -> dict:
    """Per-version quality trend for one specialist (§77): failure-rate and
    latency movement across its perf rows (version granularity)."""
    rows = db.list_specialist_perf(specialist_id)
    out = []
    for r in sorted(rows, key=lambda x: x["task_type"]):
        runs = r["runs"] or 0
        out.append({
            "task_type": r["task_type"], "version": r["version"],
            "runs": runs,
            "failure_rate": round(r["failures"] / runs, 4) if runs else None,
            "avg_latency_s": r["avg_latency_s"],
            "last_run_at": r["last_run_at"],
        })
    degraded = [o for o in out
                if o["failure_rate"] is not None and o["failure_rate"] > 0.5
                and o["runs"] >= 5]
    return {"specialist": specialist_id, "rows": out,
            "degradation_suspected": bool(degraded)}
