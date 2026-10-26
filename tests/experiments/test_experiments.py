"""Experiment framework tests (spec #34-45/#94/#145):
sandbox containment, timeouts, reproducibility, artifacts,
result -> evidence -> hypothesis update loop."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from research_engine.experiments.compare import compare_experiments
from research_engine.experiments.runner import LocalExperimentRunner


@pytest.fixture()
def runner(platform_ctx):
    return LocalExperimentRunner(platform_ctx.cfg)


GOOD_CODE = """
import json
json.dump({"accuracy": 0.82}, open("metrics.json", "w"))
open("table.csv", "w").write("model,acc\\nours,0.82\\n")
"""


class TestSandbox:
    def test_happy_path_artifacts_metrics(self, runner):
        ex = runner.execute("proj_sbx", {"code": GOOD_CODE, "seed": 42})
        assert ex.status == "COMPLETED" and ex.exit_code == 0
        assert ex.metrics == {"accuracy": 0.82}
        assert set(ex.artifacts) >= {"metrics.json", "table.csv"}
        assert ex.manifest["seed"] == 42
        assert len(ex.manifest["code_hash"]) == 16

    def test_network_denied_by_default(self, runner):
        code = ("import urllib.request\n"
                "urllib.request.urlopen('http://example.com', timeout=5)")
        ex = runner.execute("proj_sbx", {"code": code, "timeout_seconds": 20})
        assert ex.status == "FAILED"
        assert "sandbox" in ex.stderr

    def test_subprocess_denied(self, runner):
        ex = runner.execute("proj_sbx", {
            "code": "import subprocess; subprocess.run(['true'])",
            "timeout_seconds": 15})
        assert ex.status == "FAILED"

    def test_write_outside_workdir_denied(self, runner, tmp_path):
        target = tmp_path / "escape.txt"
        ex = runner.execute("proj_sbx", {
            "code": f"open({str(target)!r}, 'w').write('pwned')",
            "timeout_seconds": 15})
        assert ex.status == "FAILED"
        assert not target.exists()

    def test_timeout_kills(self, runner):
        ex = runner.execute("proj_sbx", {"code": "while True: pass",
                                         "timeout_seconds": 2})
        assert ex.timed_out and ex.duration_s < 10

    def test_no_env_leakage(self, runner, platform_ctx, monkeypatch):
        monkeypatch.setenv("GAR_SECRET_API_KEY", "supersecret123")
        ex = runner.execute("proj_sbx", {
            "code": "import os; print('KEY' in ''.join(os.environ.keys()))",
            "timeout_seconds": 15})
        assert ex.stdout.strip() == "False"


class TestReproducibility:
    def test_manifest_deterministic(self, runner):
        m1 = runner.execute("proj_r", {"code": GOOD_CODE, "seed": 7}).manifest
        m2 = runner.execute("proj_r", {"code": GOOD_CODE, "seed": 7}).manifest
        assert m1["code_hash"] == m2["code_hash"]
        assert m1["config_hash"] == m2["config_hash"]
        assert m1["python_version"] == m2["python_version"]

    def test_raw_output_never_overwritten(self, runner):
        """stdout/stderr persisted verbatim next to any interpretation."""
        ex = runner.execute("proj_r", {
            "code": "print('RAW RESULT LINE'); print('another')"})
        raw = Path(ex.workdir, "stdout.txt").read_text()
        assert "RAW RESULT LINE" in raw


class TestKnowledgeLoop:
    """design -> register -> approve -> execute -> result -> hypothesis (#34/#43/#44)."""

    @pytest.fixture()
    def wired(self, platform_ctx, make_orchestrator):
        orch = make_orchestrator("Hypothesis knowledge loop project for experiments")
        orch.run()
        from research_engine.models.reasoning import (
            Experiment, Hypothesis, Methodology,
        )
        from research_engine.storage.reasoning_repos import ReasoningRepos
        rr = ReasoningRepos(orch.db)
        h = Hypothesis(project_id=orch.project.id, title="H",
                       statement="X improves Y", type="CAUSAL",
                       origin="gap", falsification_conditions=["no effect"])
        h.ensure_id(); rr.hypotheses.save(h)
        meth = Methodology(project_id=orch.project.id, hypothesis_id=h.id,
                           tier="cheap_fast")
        meth.ensure_id()
        meth.success_condition = "accuracy_delta >= +0.03"
        meth.failure_condition = "accuracy_delta <= 0"
        rr.methodologies.save(meth)
        exp = Experiment(project_id=orch.project.id, hypothesis_id=h.id,
                         methodology_id=meth.id, title="E1")
        exp.ensure_id(); exp.status = "READY_FOR_EXECUTION"
        exp.approved_by_user = True
        rr.experiments.save(exp)
        return orch, rr, exp

    def test_execute_registered_persists_result(self, wired, platform_ctx):
        orch, rr, exp = wired
        exp.decision_note = json.dumps({"code": GOOD_CODE, "seed": 1})
        rr.experiments.save(exp)
        runner = LocalExperimentRunner(platform_ctx.cfg)
        out = runner.execute_registered(orch.project.id, exp.id)
        assert out["status"] == "COMPLETED"
        results = [r for r in _all_results(rr) if r["experiment_id"] == exp.id]
        assert results, "result row persisted"

    def test_unapproved_experiment_blocked(self, wired, platform_ctx):
        orch, rr, exp = wired
        exp.approved_by_user = False
        exp.status = "READY_FOR_HUMAN_APPROVAL"
        rr.experiments.save(exp)
        runner = LocalExperimentRunner(platform_ctx.cfg)
        out = runner.execute_registered(orch.project.id, exp.id)
        assert out["status"] == "BLOCKED"   # spec #45 human gate holds

    def test_result_ingestion_updates_hypothesis(self, wired):
        """Manual ingestion path: verdict vs pre-registered criteria (#44)."""
        orch, rr, exp = wired
        exp.status = "TESTING"
        rr.experiments.save(exp)
        from research_engine.reasoning.result_ingestion import ResultIngestor
        ing = ResultIngestor(orch.repos, rr)
        outcome = ing.ingest(
            orch.project.id, exp.id,
            observations=["accuracy improved by 0.05 on held-out set"],
            metrics={"accuracy_delta": 0.05})
        h = rr.hypotheses.get(exp.hypothesis_id)
        assert outcome.get("verdict") in ("supports", "contradicts",
                                          "inconclusive")
        assert h is not None

    def test_comparison_verdicts(self, wired):
        from research_engine.models.reasoning import Experiment
        orch, rr, exp = wired
        e2 = Experiment(project_id=orch.project.id, hypothesis_id=exp.hypothesis_id,
                        methodology_id="meth_other", title="E2")
        e2.ensure_id(); rr.experiments.save(e2)
        cmp1 = compare_experiments(rr, exp.id, e2.id)
        assert cmp1["verdict"] == "NOT_COMPARABLE_METHODOLOGY"
        cmp_self = compare_experiments(rr, exp.id, exp.id)
        assert cmp_self["same_methodology"] is True


def _all_results(rr):
    rows = rr.hypotheses.db.execute("SELECT data FROM experiment_results")
    return [json.loads(r["data"]) for r in rows]
