"""Executable proofs for Post-Stabilization Architecture Gate findings.

Findings F-01 and F-02a/b were REPAIRED in Phase-5 Phase-0; their proofs are
now HARD REGRESSIONS (an xfail here would fail-to-pass loudly if the defect
returned). Findings F-03…F-07 remain open and stay strict-xfail with their
original rationale.

Phase decision (user-approved): the gate was REPORT-ONLY for production
defects during review; repairs land as their own minimal changesets.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest


# ----------------------------------------------------------------- helpers

def _cfg(tmp_path):
    from research_engine.core.config import AppConfig
    cfg = AppConfig.load()
    cfg.storage.data_dir = str(tmp_path)
    cfg.search.web_provider = "none"
    cfg.search.academic_providers = []
    return cfg


def _startup_project(tmp_path):
    from research_engine.core.orchestrator import Orchestrator
    cfg = _cfg(tmp_path)
    orch = Orchestrator.create_project(
        cfg, "Startup research: AI bookkeeping for Indian SMB retailers",
        mode="startup")
    return orch, cfg, orch.project.id


def _store_fingerprint(paths) -> str:
    # single source of truth: logical (WAL-safe) hashing lives in the
    # INV-014 auditor module and is shared with the golden runner
    from research_engine.specialists.extension_audit import store_fingerprint
    return store_fingerprint(paths)


# ---------------------------------------------------------------- F-01
# RESOLVED: persist gate restored (duplicated block deleted), extractor
# gained persist flag, unconditioned repos-writes now honor the read-only
# convention. This is a permanent hard regression.

class TestF01ReportPurityLeak:
    """INV-004: report-path analysis must not write primary state."""

    def test_persist_false_market_context_writes_nothing(self, tmp_path):
        orch, cfg, pid = _startup_project(tmp_path)
        proj_db = pathlib.Path(orch.ws.db_path)
        kb_db = (pathlib.Path(cfg.storage.data_dir) /
                 "startup_kb" / "market_kb.sqlite")
        before = _store_fingerprint([proj_db, kb_db])

        from research_engine.specialists.startup.service import (
            StartupResearchService)
        svc = StartupResearchService(cfg=cfg,
                                     data_dir=str(cfg.storage.data_dir))
        ctx = svc.build_market_context(pid, persist=False)
        assert ctx is not None  # sanity: the read path itself works

        assert _store_fingerprint([proj_db, kb_db]) == before, (
            "persist=False market context mutated authoritative state "
            "(project db and/or cross-project KB)")


# ---------------------------------------------------------------- F-02
# RESOLVED: requeue_task is status-guarded (FAILED/DEAD_LETTER only) and
# never resets the fencing token. Both proofs are permanent regressions.

class TestF02RequeueFenceHazards:
    """Manual retry must respect single-writer ownership (INV-001/002)."""

    def _db(self):
        from research_engine.storage.platform_db import PlatformDB
        return PlatformDB(pathlib.Path(tempfile.mkdtemp()) / "data")

    def _task(self, db, max_attempts=3):
        from research_engine.models.job import ResearchJob, JobTask
        job = ResearchJob(project_id="p", type="maintenance")
        db.save_job(job)
        db.add_task(JobTask(job_id=job.id, type="WORK",
                            resource_profile="WORK",
                            max_attempts=max_attempts))
        return job

    def test_manual_requeue_rejects_live_lease(self):
        from research_engine.storage.platform_db import TaskNotRetryable
        db = self._db()
        self._task(db)
        claimed = db.claim_next_task("A", {"WORK": 1}, 60.0)
        assert claimed is not None, "task should be claimable"

        with pytest.raises(TaskNotRetryable):
            db.requeue_task(claimed.id)
        cur = db.get_task(claimed.id)
        assert cur.status in ("CLAIMED", "RUNNING"), (
            f"live lease was disturbed: status={cur.status}")
        assert cur.worker_id == "A", "ownership metadata must be untouched"

    def test_fence_token_never_decreases_across_requeue(self):
        from research_engine.storage.platform_db import StaleTaskOwner
        db = self._db()
        self._task(db, max_attempts=1)
        first = db.claim_next_task("A", {"WORK": 1}, 60.0)
        fence_before = db.get_task(first.id).attempts
        assert fence_before >= 1

        finished = db.finish_task(first.id, "A", ok=False,
                                  fence=fence_before, error="boom")
        assert finished.status == "DEAD_LETTER"

        rq = db.requeue_task(first.id)
        assert rq is not None and rq.status == "RETRYING"

        again = db.claim_next_task("B", {"WORK": 1}, 60.0)
        assert again is not None
        fence_after = db.get_task(first.id).attempts
        assert fence_after > fence_before, (
            "re-issued fence must exceed every previously issued fence; "
            f"before={fence_before} after={fence_after}")

        # the FIRST execution's writer+token stays stale forever
        with pytest.raises(StaleTaskOwner):
            db.finish_task(first.id, "A", ok=True, fence=fence_before)


# ---------------------------------------------------------------- F-03

class TestF03ExperimentGroundingBypass:
    """INV-005 undocumented carve-out: result_ingestion.py:63-78 persists
    experiment-derived Evidence as tier-1 / SUPPORTED / confidence=0.85
    without passing either grounding gate (quote verification never runs;
    support_verdict stays empty). The row even carries the legacy 0.7
    SUPPORT_FACTOR weight. Whatever the provenance argument for
    user-provided results, the exception exists nowhere in
    docs/invariants.md — it silently diverges from the canonical rule."""

    @pytest.mark.xfail(strict=True, reason=(
        "GATE F-03: experiment ingestion persists ungrounded tier-1 "
        "SUPPORTED evidence; no documented INV-005 carve-out"))
    def test_ingested_experiment_evidence_carries_support_verdict(
            self, tmp_path):
        orch, cfg, pid = _startup_project(tmp_path)

        from research_engine.models.reasoning import Experiment
        from research_engine.storage.reasoning_repos import ReasoningRepos
        rr = ReasoningRepos(orch.db)
        exp = Experiment(project_id=pid, title="Pricing page A/B",
                         hypothesis_id="", methodology_id="")
        exp.ensure_id()
        rr.experiments.save(exp)

        from research_engine.reasoning.result_ingestion import ResultIngestor
        err = None
        try:
            ResultIngestor(orch.repos, rr).ingest(
                pid, exp.id,
                observations=["conversion improved to 9%"],
                metrics={"conversion": 0.09},
                raw_notes="user-run notebook output; raw metrics attached")
        except Exception as e:
            err = e
        assert err is None, f"ingest path crashed: {err!r}"

        evs = [e for e in orch.repos.evidence.all(pid)
               if str(getattr(e, "source_title", "")).startswith("experiment:")]
        assert evs, "experiment evidence row was not persisted"
        ev = evs[-1]
        assert getattr(ev, "support_verdict", "") != "", (
            "INV-005 requires a support verdict (or an explicit documented "
            f"provenance carve-out); got status={ev.status} "
            f"tier={ev.source_tier} confidence={ev.confidence}")


# ---------------------------------------------------------------- F-04

class TestF04ConvergenceTiebreakerOutage:
    """INV-006 path hole: convergence.py:90 calls provider.structured()
    unguarded inside the LLM tiebreaker. A transient LLM outage there raises
    LLMError up through evaluate(); orchestrator.py converts the escape into
    project FAILED — honest degradation (PROVIDER_DEGRADED) is defeated on
    this path."""

    @pytest.mark.xfail(strict=True, reason=(
        "GATE F-04: unguarded LLM tiebreaker escalates outage to raised "
        "error instead of honest degradation"))
    def test_llm_outage_during_tiebreaker_degrades_not_raises(self):
        from research_engine.core.budget import Budget
        from research_engine.models.enums import StopReason
        from research_engine.models.project import ResearchProject
        from research_engine.providers.llm.base import LLMError
        from research_engine.reasoning.convergence import ConvergenceAnalyzer

        class DeadProvider:
            def structured(self, *a, **k):
                raise LLMError("ollama unreachable")

        cfg = _cfg(tempfile.mkdtemp())
        proj = ResearchProject(id="proj_x", question_raw="q")
        budget = Budget(cfg, proj)
        stats = {
            # falls through every deterministic branch into the tiebreaker
            "total_evidence": 20, "new_evidence": 6,
            "fetch_successes": 6, "fetch_failures": 0,
            "queries_executed": 8,
            "duplicate_rate": 0.1, "rejection_rate": 0.1,
            "high_importance_gaps": 2, "new_claims": 2, "domains": 4,
        }
        decision = ConvergenceAnalyzer(
            cfg, provider=DeadProvider()).evaluate(proj, budget, stats)
        assert decision.stop_reason != StopReason.CONVERGED


# ---------------------------------------------------------------- F-05

class TestF05FailureConflationCensus:
    """INV-012 violations: search/academic providers swallow exceptions and
    `return []`, conflating FAILED with NO_RESULTS. Downstream, retrieval
    caches the empty page globally (TTL hours, shared across projects), so
    one transient outage poisons identical queries in unrelated projects.
    Confirmed sites include arxiv.py:39, crossref.py:56,
    semantic_scholar.py:31/:52, openalex.py:59."""

    @staticmethod
    def _census(root: pathlib.Path) -> list[str]:
        """AST-precise: an except handler whose body ends a path with a bare
        `return []` (no raise) conflates failure with empty success."""
        import ast
        offenders: list[str] = []

        class V(ast.NodeVisitor):
            def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
                for child in node.body:
                    if (isinstance(child, ast.Return)
                            and isinstance(child.value, ast.List)
                            and not child.value.elts):
                        offenders.append(f"{node.lineno}")
                        break
                self.generic_visit(node)

        for p in sorted(root.rglob("*.py")):
            before = len(offenders)
            V().visit(ast.parse(p.read_text()))
            n_new = len(offenders) - before
            if n_new:
                offenders[before:] = [f"{p.relative_to(root)}:{s}"
                                      for s in offenders[before:]]
        return offenders

    @pytest.mark.xfail(strict=True, reason=(
        "GATE F-05: provider except-blocks end in bare 'return []', "
        "conflating failure with empty success (INV-012)"))
    def test_no_bare_empty_return_in_provider_except_blocks(self):
        root = (pathlib.Path(__file__).resolve().parents[2] /
                "src" / "research_engine" / "providers")
        offenders = self._census(root)
        assert not offenders, (
            "provider failure conflated to [] at: " + ", ".join(offenders))


# ---------------------------------------------------------------- F-06

class TestF06AntonymInversionUndetected:
    """NEW finding from gate §14 matrix extension: the claim-support
    violation lexicon catches explicit negation tokens ("not effective")
    but has no antonym/direction pairs, so a quote saying the OPPOSITE of
    the claim on a metric direction ("increased" vs "decreased") scores
    STRONGLY_SUPPORTS on vocabulary overlap alone."""

    @pytest.mark.xfail(strict=True, reason=(
        "GATE F-06: no antonym/direction-inversion detection in "
        "claim_support; opposite-direction quotes strongly support"))
    def test_metric_direction_flip_contradicts(self):
        from research_engine.pipeline.claim_support import verify_claim_support
        r = verify_claim_support(
            "Churn decreased after the onboarding redesign.",
            "Churn increased after the onboarding redesign.")
        assert r.verdict == "CONTRADICTS", r.reasons


# ---------------------------------------------------------------- F-07

class TestF07OpportunityPricingSignalLinkage:
    """NEW finding from the startup golden baseline (§23/§42 traceability):
    PricingPlan rows DO carry evidence_id links, and opportunities DO carry
    core pain evidence_ids — but pricing_evidence_ids and
    market_signal_evidence_ids stay EMPTY on every materialized opportunity,
    even when matching pricing/signal artifacts sit in the same store.
    Opportunity traceability is therefore partial."""

    @pytest.mark.xfail(strict=True, reason=(
        "GATE F-07: materialized opportunities never link pricing/signal "
        "evidence though such evidence exists in-store"))
    def test_opportunities_link_pricing_or_signal_evidence(self, tmp_path):
        from research_engine.core.config import AppConfig
        from research_engine.core.orchestrator import Orchestrator
        cfg = AppConfig.load()
        cfg.storage.data_dir = str(tmp_path)
        cfg.search.web_provider = "none"
        cfg.search.academic_providers = []
        Q = ("Find promising startup opportunities in AI bookkeeping "
             "software for Indian SMB retailers")
        orch = Orchestrator.create_project(cfg, Q, mode="startup")
        pid = orch.project.id

        from research_engine.models.evidence import Evidence
        from research_engine.models.research import Source
        s = Source(project_id=pid, url="https://f.example.com/1",
                   canonical_url="https://f.example.com/1",
                   domain="f.example.com", title="t")
        s.ensure_id()
        orch.repos.sources.save(s)
        for claim in [
            "Retailers complain bookkeeping is manual and time-consuming weekly",
            "Shop owners paying accountants 15000 rupees per month",
            "Zoho Books charges 15 dollars per month",
        ]:
            e = Evidence(project_id=pid, claim_text=claim, quote=claim[:40],
                         source_id=s.id, source_tier=4, status="EXTRACTED")
            e.ensure_id()
            orch.repos.evidence.save(e)

        from research_engine.specialists.startup.service import (
            StartupResearchService)
        StartupResearchService(cfg=cfg, data_dir=str(tmp_path)) \
            .run_full_pipeline(pid)

        from research_engine.specialists.startup.repos import (
            get_startup_repos)
        srepos = get_startup_repos(orch)
        opps = orch.repos.opportunities.all(pid)
        assert opps, "pipeline produced no opportunities"
        assert any(o.pricing_evidence_ids or o.market_signal_evidence_ids
                   for o in opps), (
            f"no opportunity links pricing/signal evidence; plans in store: "
            f"{len(srepos.pricing_plans.all(pid))}")
