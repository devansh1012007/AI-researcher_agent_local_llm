"""Evaluation runner.

Usage (offline, deterministic):
    python evals/runners/run_eval.py --offline            # scripted fakes
    python evals/runners/run_eval.py --task golden_llm_manipulation   # live network

Scores are computed from persisted state via evals.metrics.eval_metrics.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

from research_engine.core.config import AppConfig  # noqa: E402
from research_engine.storage.database import Database  # noqa: E402
from research_engine.storage.repositories import Repositories  # noqa: E402
from evals.metrics.eval_metrics import score_project  # noqa: E402


def load_tasks(path: Path) -> list[dict]:
    return json.loads(path.read_text())["tasks"]


def run_offline(task: dict, cfg: AppConfig):
    """Deterministic offline run through fakes, in an ISOLATED fresh workspace.

    Project ids derive from the question, so reruns would otherwise reopen a
    stale DB where per-process ID counters collide with old rows.
    """
    import tempfile as _t
    fresh = _t.mkdtemp(prefix="gar_eval_")
    cfg.storage.data_dir = str(Path(fresh) / "data")
    from conftest import OfflineOrchestrator
    from research_engine.pipeline.routing import ProviderRegistry
    from fakes import FakeAcademicProvider, FakeSearchProvider
    from research_engine.models.project import ResearchProject
    from research_engine.core.ids import project_id_from_question

    reg = ProviderRegistry()
    reg.register_search("web", FakeSearchProvider(hits_per_query=3))
    for n in ("openalex", "arxiv", "crossref", "semantic_scholar"):
        reg.register_academic(n, FakeAcademicProvider(n=2))
    project = ResearchProject(id=project_id_from_question(task["question"]),
                              question_raw=task["question"], mode=task["mode"])
    orch = OfflineOrchestrator(cfg, project, reg)
    orch.repos.projects.save(orch.project)
    t0 = time.time()
    orch.run()
    return orch, time.time() - t0


def run_live(task: dict, cfg: AppConfig):
    """Live run: real network; LLM roles use whatever gar.yaml configures."""
    from research_engine.core.orchestrator import Orchestrator
    orch = Orchestrator.create_project(cfg, task["question"], mode=task["mode"])
    t0 = time.time()
    orch.run()
    return orch, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="deterministic offline run")
    ap.add_argument("--task", default=None, help="run a single task id")
    ap.add_argument("--dataset", default=None, help="defaults to all dataset files")
    args = ap.parse_args()

    if args.dataset:
        files = [Path(args.dataset)]
    else:
        files = sorted((ROOT / "evals/datasets").glob("*.json"))
    tasks = []
    for f in files:
        tasks.extend(load_tasks(f))
    if args.task:
        tasks = [t for t in tasks if t["id"] == args.task]

    results = []
    for task in tasks:
        cfg = AppConfig.load()
        cfg.research.max_iterations = 1 if args.offline else cfg.research.max_iterations
        print(f"\n=== {task['id']} ({task['mode']}) ===")
        print(f"Q: {task['question']}")
        if args.offline:
            orch, secs = run_offline(task, cfg)
        else:
            orch, secs = run_live(task, cfg)
        repos = orch.repos
        scores = score_project(repos, orch.project.id,
                               task.get("expected_subquestions"))
        scores.wall_clock_seconds = secs
        q = task.get("quality_expectations", {})
        failures = []
        if q.get("min_primary_ratio") and scores.primary_source_ratio < q["min_primary_ratio"]:
            failures.append("primary_ratio")
        if q.get("min_citation_coverage") and scores.citation_coverage < q["min_citation_coverage"]:
            failures.append("citation_coverage")
        if q.get("min_quote_correctness") and scores.quote_correctness < q["min_quote_correctness"]:
            failures.append("quote_correctness")
        if task.get("expect_gaps") and not scores.gaps_discovered:
            failures.append("expected_gaps_but_none_found")
        # Phase 4 lifecycle gate: project must reach a clean terminal state
        if task.get("expect_completed"):
            state = orch.project.state.value
            if state != "COMPLETED":
                failures.append(f"lifecycle_state_{state}")
            if not getattr(orch, "ws", None) or                not any((orch.ws.reports).glob("*.md")):
                failures.append("no_reports_generated")
        status = "PASS" if not failures else f"FAIL({','.join(failures)})"
        print(scores.summary())
        print(f"quality gates: {status}")
        results.append({"task": task["id"], "status": status,
                        "scores": {k: v for k, v in scores.__dict__.items() if k != "notes"}})

    out = ROOT / "evals" / "last_eval_results.json"
    out.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nResults written to {out}")


if __name__ == "__main__":
    main()
