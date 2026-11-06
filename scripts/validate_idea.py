#!/usr/bin/env python3
"""Evaluate ONE startup idea with the `startup_validation` engine.

Builds the idea card, creates the project and (unless --no-run) runs the full research loop.
Equivalent to:  research new --engine startup_validation "<card text>"

  python scripts/validate_idea.py "AI bookkeeping for Indian kirana stores" \
      --problem "owners spend hours on manual GST entries" \
      --customer-segment "kirana store owners in India" \
      --alternative "Tally and a part-time accountant" \
      --price-point "Rs 500 per month" \
      --riskiest-assumption "owners will trust AI with GST filings" \
      --founder-constraints "skills=python,ml; capital=bootstrap; time=15 hours per week"

Use --print-only to see the card without creating a project.

After running real tests, record each result with `research add-result <project> <experiment>`
(experiment ids are in validation_plan.md), then re-read the verdict. No new research is run:

  python scripts/validate_idea.py --reevaluate <project_id>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_engine.specialists.startup.idea import CARD_KEYS, build_idea_question  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("idea", nargs="?", default="", help="the idea in one line")
    ap.add_argument("--reevaluate", metavar="PROJECT_ID", default="",
                    help="re-read the verdict and rewrite idea_evaluation.md after add-result")
    for key in CARD_KEYS:
        ap.add_argument("--" + key.replace("_", "-"), dest=key, default="")
    ap.add_argument("--print-only", action="store_true", help="print the idea card and exit")
    ap.add_argument("--no-run", action="store_true", help="create the project but do not run it")
    return ap


def reevaluate(project_id: str, cfg=None) -> int:
    """READ-ONLY re-evaluation: ingested experiment results change the verdict, nothing is re-run."""
    from research_engine.core.config import AppConfig
    from research_engine.specialists.startup.reports import StartupReportWriter
    from research_engine.specialists.startup.service import StartupResearchService
    cfg = cfg or AppConfig.load()
    svc = StartupResearchService(cfg=cfg, data_dir=cfg.storage.data_dir)
    view = svc.idea_evaluation_view(project_id)
    reports = svc._orch(project_id).ws.reports
    path = StartupReportWriter(reports).write_idea_evaluation(view)
    verdict = (view.get("verdict") or {}).get("verdict", "NO_VERDICT")
    print(f"verdict: {verdict}\nreport: {path}")
    return 0 if view.get("verdict") else 1


def main(argv: list[str] | None = None, cfg=None) -> int:
    args = build_parser().parse_args(argv)
    if args.reevaluate:
        return reevaluate(args.reevaluate, cfg)
    if not args.idea.strip():
        print("error: give an idea, or --reevaluate PROJECT_ID", file=sys.stderr)
        return 2
    try:
        card = build_idea_question(args.idea, **{k: getattr(args, k) for k in CARD_KEYS})
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.print_only:
        print(card)
        return 0
    from research_engine.core.config import AppConfig
    from research_engine.core.orchestrator import Orchestrator
    orch = Orchestrator.create_project(cfg or AppConfig.load(), card, mode="startup_validation")
    print(f"project: {orch.project.id}")
    if args.no_run:
        return 0
    project = orch.run()
    print(f"state: {project.state.value}")
    print(f"report: {orch.ws.reports / 'idea_evaluation.md'}")
    return 0 if project.state.value == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
