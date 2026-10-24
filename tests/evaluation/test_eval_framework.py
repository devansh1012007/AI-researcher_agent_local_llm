"""Evaluation framework test: golden tasks pass deterministic quality gates offline."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

from research_engine.core.config import AppConfig
from research_engine.storage.database import Database
from research_engine.storage.repositories import Repositories
from research_engine.models.evidence import Evidence
from research_engine.models.enums import EvidenceStatus
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


def test_duplicate_rate_uses_duplicate_ratio_not_rejection(tmp_path):
    """C18: duplicate_rate must be the true duplicate_ratio, not rejected_ratio.

    Builds accepted evidence with a repeated quote hash (one duplicate) and no
    rejections, so rejected_ratio == 0.0 while duplicate_ratio == 1/3. The two
    metrics differ, which pins down the correct source of duplicate_rate.
    """
    db = Database(tmp_path / "t.sqlite")
    repos = Repositories(db)
    pid = "p-dup-rate"

    repos.evidence.save(Evidence(project_id=pid, claim_text="c1", quote="alpha beta gamma",
                                 source_id="s1", status=EvidenceStatus.SUPPORTED, iteration=1))
    repos.evidence.save(Evidence(project_id=pid, claim_text="c2", quote="alpha beta gamma",
                                 source_id="s2", status=EvidenceStatus.SUPPORTED, iteration=2))
    repos.evidence.save(Evidence(project_id=pid, claim_text="c3", quote="delta epsilon zeta",
                                 source_id="s3", status=EvidenceStatus.SUPPORTED, iteration=3))

    assert repos.evidence.rejected_ratio(pid) == 0.0
    assert abs(repos.evidence.duplicate_ratio(pid) - (1 / 3)) < 1e-9

    s = score_project(repos, pid)
    assert s.duplicate_rate == repos.evidence.duplicate_ratio(pid)
    assert s.duplicate_rate != repos.evidence.rejected_ratio(pid)
