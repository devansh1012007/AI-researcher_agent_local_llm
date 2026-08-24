"""Evaluation framework test: golden tasks pass deterministic quality gates offline."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

from research_engine.core.config import AppConfig
from evals.metrics.eval_metrics import score_project
from evals.runners.run_eval import load_tasks, run_offline


def test_golden_tasks_offline_gates(tmp_path):
    tasks = load_tasks(ROOT / "evals/datasets/golden_tasks.json")
    assert len(tasks) >= 5
    failures = []
    for task in tasks:
        cfg = AppConfig.load()
        cfg.storage.data_dir = str(tmp_path / task["id"])
        cfg.research.max_iterations = 1
        orch, _ = run_offline(task, cfg)
        s = score_project(orch.repos, orch.project.id,
                          task.get("expected_subquestions"))
        q = task.get("quality_expectations", {})
        if q.get("min_citation_coverage") and s.citation_coverage < q["min_citation_coverage"]:
            failures.append(f"{task['id']}: citation_coverage={s.citation_coverage}")
        if q.get("min_quote_correctness") and s.quote_correctness < q["min_quote_correctness"]:
            failures.append(f"{task['id']}: quote_correctness={s.quote_correctness}")
        # universal grounding invariants
        ev = orch.repos.evidence.all(orch.project.id)
        accepted = [e for e in ev if e.status.value != "REJECTED"]
        for e in accepted:
            assert e.source_url, f"{task['id']}: evidence without source url"
            assert e.source_id and e.document_id, f"{task['id']}: broken provenance chain"
    assert not failures, "; ".join(failures)
