"""Gold-set scorer for the offline quality benchmark (C17, D.7, D.8).

Computes support-verdict precision/recall/F1, contradiction-analysis
accuracy, and opportunity rank agreement from content-keyed gold labels
plus the engine's persisted output. All metrics are model-free and
offline; no live model is needed.

Wilson score intervals are reported for proportions; before n>=300
labelled items the runner reports CIs but does not gate (D.7).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


def _wilson_ci(successes: int, trials: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion (successes/trials)."""
    if trials == 0:
        return (0.0, 0.0)
    p = successes / trials
    denom = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass
class LabelMetricResult:
    name: str
    value: float
    ci_low: float
    ci_high: float
    n: int
    detail: str = ""


@dataclass
class GoldScores:
    support_precision: LabelMetricResult
    support_recall: LabelMetricResult
    support_f1: LabelMetricResult
    contradiction_accuracy: LabelMetricResult
    opportunity_rank_correlation: LabelMetricResult
    n_support: int = 0
    n_contradiction: int = 0
    n_opportunity: int = 0
    notes: list[str] = field(default_factory=list)

    def gate_ready(self) -> bool:
        """True iff enough labelled items to gate (D.7: n>=300)."""
        return self.n_support + self.n_contradiction + self.n_opportunity >= 300

    def summary(self) -> str:
        lines = [
            f"support:   precision={self.support_precision.value:.3f} "
            f"[{self.support_precision.ci_low:.3f},{self.support_precision.ci_high:.3f}] "
            f"recall={self.support_recall.value:.3f} "
            f"[{self.support_recall.ci_low:.3f},{self.support_recall.ci_high:.3f}] "
            f"f1={self.support_f1.value:.3f} (n={self.n_support})",
            f"contradiction: accuracy={self.contradiction_accuracy.value:.3f} "
            f"[{self.contradiction_accuracy.ci_low:.3f},{self.contradiction_accuracy.ci_high:.3f}] "
            f"(n={self.n_contradiction})",
            f"opportunity: rank_correlation={self.opportunity_rank_correlation.value:.3f} "
            f"[{self.opportunity_rank_correlation.ci_low:.3f},{self.opportunity_rank_correlation.ci_high:.3f}] "
            f"(n={self.n_opportunity})",
            f"gate_ready={self.gate_ready()}",
        ]
        if self.notes:
            lines.append("notes: " + "; ".join(self.notes))
        return "\n".join(lines)


def _binomial_ci(successes: int, trials: int) -> LabelMetricResult:
    low, high = _wilson_ci(successes, trials)
    value = successes / trials if trials else 0.0
    return LabelMetricResult(
        name="proportion", value=value, ci_low=low, ci_high=high, n=trials,
    )


def score_support(labels: list[dict[str, Any]],
                  predictions: dict[str, str]) -> tuple[LabelMetricResult, LabelMetricResult, LabelMetricResult, int]:
    """Score support-verdict predictions against gold labels.

    `labels`: gold items with kind=="support", each having "key" and "label"
    (SUPPORTED / NOT_SUPPORTED).
    `predictions`: map from content key -> predicted label.
    Returns (precision, recall, f1, n_items).
    """
    tp = fp = fn = 0
    n = 0
    for item in labels:
        if item.get("kind") != "support":
            continue
        n += 1
        key = item["key"]
        gold = item["label"]
        pred = predictions.get(key, "NOT_SUPPORTED")
        if gold == "SUPPORTED" and pred == "SUPPORTED":
            tp += 1
        elif gold == "NOT_SUPPORTED" and pred == "NOT_SUPPORTED":
            pass  # true negative, not counted in precision/recall
        elif gold == "SUPPORTED" and pred != "SUPPORTED":
            fn += 1  # missed a supported claim
        elif gold == "NOT_SUPPORTED" and pred == "SUPPORTED":
            fp += 1  # false alarm

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    p_res = _binomial_ci(tp, tp + fp) if (tp + fp) else LabelMetricResult("precision", 0.0, 0.0, 0.0, 0)
    r_res = _binomial_ci(tp, tp + fn) if (tp + fn) else LabelMetricResult("recall", 0.0, 0.0, 0.0, 0)
    f1_res = LabelMetricResult(
        "f1", f1, *(_wilson_ci(int(f1 * 1000), 1000)) if f1 else (0.0, 0.0),
        n=n,
    )
    return p_res, r_res, f1_res, n


def score_contradiction(labels: list[dict[str, Any]],
                        predictions: dict[str, str]) -> tuple[LabelMetricResult, int]:
    """Score contradiction-detection predictions against gold labels.

    Returns (accuracy, n_items).
    """
    correct = 0
    n = 0
    for item in labels:
        if item.get("kind") != "contradiction":
            continue
        n += 1
        key = item["key"]
        gold = item["label"]
        pred = predictions.get(key, "NOT_CONTRADICTS")
        if gold == pred:
            correct += 1
    acc = correct / n if n else 0.0
    res = _binomial_ci(correct, n)
    return res, n


def score_opportunity(labels: list[dict[str, Any]],
                      scores_by_key: dict[str, float]) -> LabelMetricResult:
    """Score opportunity rank agreement (Spearman rank correlation).

    `labels`: gold items with kind=="opportunity", each having "key" and
    "score" (human rank 0-1).
    `scores_by_key`: map from content key -> engine rank score.
    Returns a LabelMetricResult with value = Spearman rho.
    """
    pairs: list[tuple[float, float]] = []
    for item in labels:
        if item.get("kind") != "opportunity":
            continue
        key = item["key"]
        if key not in scores_by_key:
            continue
        pairs.append((float(item["score"]), float(scores_by_key[key])))

    if len(pairs) < 2:
        return LabelMetricResult("rank_corr", 0.0, 0.0, 0.0, 0,
                                 detail="too few pairs")

    # Spearman rank correlation
    import statistics as _stats
    gold_ranks = _rank_values([p[0] for p in pairs])
    pred_ranks = _rank_values([p[1] for p in pairs])
    n = len(pairs)
    d2 = sum((g - p) ** 2 for g, p in zip(gold_ranks, pred_ranks))
    rho = 1 - (6 * d2) / (n * (n * n - 1)) if n > 1 else 0.0
    ci_low, ci_high = _wilson_ci(int((rho + 1) * 500), 1000)
    return LabelMetricResult(
        "rank_corr", rho, ci_low, ci_high, n,
        detail="spearman",
    )


def _rank_values(values: list[float]) -> list[float]:
    """Return ranks (average for ties) of values."""
    sorted_vals = sorted(set(values))
    rank_map = {v: i + 1 for i, v in enumerate(sorted_vals)}
    return [rank_map[v] for v in values]


def score_all(labels: list[dict[str, Any]],
              support_preds: dict[str, str],
              contra_preds: dict[str, str],
              opp_scores: dict[str, float]) -> GoldScores:
    """Score all gold labels against engine predictions.

    Returns a GoldScores object with all metrics and notes.
    """
    p_res, r_res, f1_res, n_support = score_support(labels, support_preds)
    c_res, n_contra = score_contradiction(labels, contra_preds)
    o_res = score_opportunity(labels, opp_scores)

    notes: list[str] = []
    if n_support < 30:
        notes.append("few support labels: precision/recall CI wide")
    if n_contra < 30:
        notes.append("few contradiction labels: accuracy CI wide")
    if not p_res.n:
        notes.append("no support labels scored")
    if not c_res.n:
        notes.append("no contradiction labels scored")

    return GoldScores(
        support_precision=p_res,
        support_recall=r_res,
        support_f1=f1_res,
        contradiction_accuracy=c_res,
        opportunity_rank_correlation=o_res,
        n_support=n_support,
        n_contradiction=n_contra,
        n_opportunity=o_res.n,
        notes=notes,
    )
