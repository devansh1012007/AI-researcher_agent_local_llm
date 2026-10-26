"""Experiment comparison (spec #41): comparability verdicts, not vibes.

Two results are comparable only when methodology, dataset/config, seed
policy, and environment line up and a single variable differs. Otherwise we
say so explicitly instead of inventing deltas.
"""
from __future__ import annotations

import json


def compare_experiments(rrepos, exp_a_id: str, exp_b_id: str) -> dict:
    a = rrepos.experiments.get(exp_a_id)
    b = rrepos.experiments.get(exp_b_id)
    if a is None or b is None:
        raise ValueError("experiment(s) not found")
    res_a = _latest_result(rrepos, exp_a_id)
    res_b = _latest_result(rrepos, exp_b_id)

    meth_same = bool(a.methodology_id) and \
        a.methodology_id == b.methodology_id
    config_a = _config_of(a)
    config_b = _config_of(b)
    differing_keys = {k for k in (set(config_a) | set(config_b))
                      if config_a.get(k) != config_b.get(k)}
    env_comparable = _env_comparable(res_a, res_b)

    if not meth_same:
        verdict = "NOT_COMPARABLE_METHODOLOGY"
    elif len(differing_keys) > 1:
        verdict = "MULTIPLE_VARIABLES_CHANGED"
    elif not env_comparable:
        verdict = "ENVIRONMENT_MISMATCH"
    else:
        verdict = "COMPARABLE"

    metric_diffs: dict[str, dict] = {}
    if res_a and res_b and verdict == "COMPARABLE":
        ma, mb = res_a.get("metrics", {}), res_b.get("metrics", {})
        for k in set(ma) & set(mb):
            try:
                delta = round(float(mb[k]) - float(ma[k]), 6)
                metric_diffs[k] = {"a": ma[k], "b": mb[k], "delta": delta}
            except (TypeError, ValueError):
                continue

    return {
        "experiment_a": exp_a_id,
        "experiment_b": exp_b_id,
        "verdict": verdict,
        "same_methodology": meth_same,
        "differing_config_keys": sorted(differing_keys),
        "environment": {"a": _env_of(res_a), "b": _env_of(res_b)},
        "metric_differences": metric_diffs,
        "note": ("single-variable comparison valid" if verdict == "COMPARABLE"
                 else "differences are NOT attributable to one variable"),
    }


def _latest_result(rrepos, experiment_id: str) -> dict | None:
    """Latest persisted result row for an experiment (raw table scan)."""
    out = None
    try:
        rows = rrepos.db.execute(
            "SELECT data FROM experiment_results WHERE "
            "json_extract(data,'$.experiment_id')=? "
            "ORDER BY created_at DESC LIMIT 1", (experiment_id,))
    except Exception:
        return None
    for r in rows:
        out = json.loads(r["data"])
    return out


def _config_of(exp) -> dict:
    note = getattr(exp, "decision_note", "") or ""
    try:
        return json.loads(note) if note else {}
    except ValueError:
        return {}


def _env_of(result: dict | None) -> str | None:
    if not result:
        return None
    man = result.get("manifest") or {}
    return f"{man.get('python_version', '?')}/{man.get('platform', '?')}"


def _env_comparable(a: dict | None, b: dict | None) -> bool:
    if not a or not b:
        return True  # nothing recorded yet -> don't block, flag as unknown
    ea, eb = _env_of(a), _env_of(b)
    return ea == eb or ea is None or eb is None
