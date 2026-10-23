"""Offline gold-set quality benchmark runner (C17, D.7, D.8).

Usage:
    python evals/runners/run_goldset.py          # offline, hermetic
    python evals/runners/run_goldset.py --live   # operator-invoked, needs a model (never gates)

Writes evals/gold/last_goldset_results.json (never evals/last_eval_results.json).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

from evals.gold.fixtures import load_gold_items, write_starter_fixtures  # noqa: E402
from evals.metrics.label_metrics import score_all  # noqa: E402


def _engine_support_predictions(labels: list[dict]) -> dict[str, str]:
    """Engine's support predictions for gold items.

    Placeholder: in the offline tier the engine's claim-support verifier
    (pipeline.claim_support.verify_claim_support) is deterministic and
    model-free, so predictions can be computed without a live model.
    This stub returns NOT_SUPPORTED for everything until the verifier is
    wired per item key; replace with real lookups keyed by content hash.
    """
    return {item["key"]: "NOT_SUPPORTED" for item in labels if item.get("kind") == "support"}


def _engine_contradiction_predictions(labels: list[dict]) -> dict[str, str]:
    """Engine's contradiction predictions for gold items.

    Stub returns NOT_CONTRADICTS for everything until the contradiction
    detector is wired per item key.
    """
    return {item["key"]: "NOT_CONTRADICTS" for item in labels if item.get("kind") == "contradiction"}


def _engine_opportunity_scores(labels: list[dict]) -> dict[str, float]:
    """Engine's opportunity rank scores for gold items.

    Stub returns 0.5 for everything until the opportunity scorer is wired.
    """
    return {item["key"]: 0.5 for item in labels if item.get("kind") == "opportunity"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline gold-set quality benchmark")
    parser.add_argument("--live", action="store_true",
                        help="live tier: operator-invoked, needs a model, reports detection recall, never gates")
    args = parser.parse_args(argv)

    fixtures_path = write_starter_fixtures()
    labels = load_gold_items(fixtures_path)

    support_preds = _engine_support_predictions(labels)
    contra_preds = _engine_contradiction_predictions(labels)
    opp_scores = _engine_opportunity_scores(labels)

    scores = score_all(labels, support_preds, contra_preds, opp_scores)

    out = {
        "n_support": scores.n_support,
        "n_contradiction": scores.n_contradiction,
        "n_opportunity": scores.n_opportunity,
        "gate_ready": scores.gate_ready(),
        "support_precision": scores.support_precision.value,
        "support_precision_ci": [scores.support_precision.ci_low, scores.support_precision.ci_high],
        "support_recall": scores.support_recall.value,
        "support_recall_ci": [scores.support_recall.ci_low, scores.support_recall.ci_high],
        "support_f1": scores.support_f1.value,
        "contradiction_accuracy": scores.contradiction_accuracy.value,
        "contradiction_accuracy_ci": [scores.contradiction_accuracy.ci_low, scores.contradiction_accuracy.ci_high],
        "opportunity_rank_correlation": scores.opportunity_rank_correlation.value,
        "opportunity_rank_correlation_ci": [scores.opportunity_rank_correlation.ci_low, scores.opportunity_rank_correlation.ci_high],
        "notes": scores.notes,
    }

    out_path = Path(__file__).resolve().parent.parent / "gold" / "last_goldset_results.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(scores.summary())
    print(f"\nResults written to {out_path}")
    if args.live:
        print("Live tier: reported, not gated (D.8)")
    elif not scores.gate_ready():
        print("Gate not ready (n<300): reporting CIs only (D.7)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
