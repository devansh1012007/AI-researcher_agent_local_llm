"""Knowledge services: evidence, claims, gaps, hypotheses, reports, experiments.

Read paths are thin, paginated projections over repos — interfaces never see
SQLite. Write paths enforce the same policies the CLI enforces (human gates,
pre-registered criteria).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from research_engine.models.job import (
    JobPriority, JobTask, ResourceProfile,
)
from research_engine.platform.events import DomainEvent
from research_engine.services.research_service import NotFoundError


def _orch(ctx, project_id: str):
    from research_engine.core.orchestrator import Orchestrator
    try:
        return Orchestrator.load(ctx.cfg, project_id)
    except FileNotFoundError as exc:
        raise NotFoundError("project", project_id) from exc


def _rrepos(orch):
    from research_engine.storage.reasoning_repos import ReasoningRepos
    if not hasattr(orch, "_rrepos"):
        orch._rrepos = ReasoningRepos(orch.db)
    return orch._rrepos


class KnowledgeService:
    """Aggregating facade over the knowledge services (single seam for
    MCP/CLI callers that need cross-area operations)."""

    def __init__(self, ctx):
        self.ctx = ctx

    @property
    def evidence(self) -> "EvidenceService":
        return EvidenceService(self.ctx)

    @property
    def hypotheses(self) -> "HypothesisService":
        return HypothesisService(self.ctx)

    @property
    def reports(self) -> "ReportService":
        return ReportService(self.ctx)

    @property
    def experiments(self) -> "ExperimentService":
        return ExperimentService(self.ctx)

    # canonical operations (P0-11: one authoritative path per action)
    def design_methodology(self, project_id: str, hypothesis_id: str) -> list[dict]:
        return self.hypotheses.design_methodology(project_id, hypothesis_id)

    def generate_hypotheses(self, project_id: str) -> dict:
        return self.hypotheses.generate(project_id)

    def approve_experiment(self, project_id: str, experiment_id: str,
                           approved: bool, note: str = "") -> dict:
        return self.experiments.approve(project_id, experiment_id,
                                        approved=approved, note=note)


class EvidenceService:
    def __init__(self, ctx):
        self.ctx = ctx

    def list_evidence(self, project_id: str, offset=0, limit=50,
                      status: str = "") -> dict:
        orch = _orch(self.ctx, project_id)
        where = "status!='REJECTED'" if not status else f"status='{status}'"
        items = [json.loads(e.model_dump_json())
                 for e in orch.repos.evidence.all(project_id, where, ())]
        return {"items": items[offset:offset + limit], "total": len(items),
                "offset": offset, "limit": limit}

    def get_evidence(self, project_id: str, evidence_id: str) -> dict:
        orch = _orch(self.ctx, project_id)
        e = orch.repos.evidence.get(evidence_id)
        if e is None or e.project_id != project_id:
            raise NotFoundError("evidence", evidence_id)
        out = json.loads(e.model_dump_json())
        src = orch.repos.sources.get(e.source_id)
        out["source"] = json.loads(src.model_dump_json()) if src else None
        return out

    def list_claims(self, project_id: str, offset=0, limit=50) -> dict:
        orch = _orch(self.ctx, project_id)
        items = [json.loads(c.model_dump_json()) for c in orch.repos.claims.all(project_id)]
        return {"items": items[offset:offset + limit], "total": len(items),
                "offset": offset, "limit": limit}

    def trace_claim(self, project_id: str, claim_id: str) -> list[dict]:
        """Full provenance chain claim -> evidence -> source (spec #50/#77)."""
        orch = _orch(self.ctx, project_id)
        chain = []
        claim = orch.repos.claims.get(claim_id)
        if claim is None or claim.project_id != project_id:
            raise NotFoundError("claim", claim_id)
        for eid in claim.evidence_ids:
            ev = orch.repos.evidence.get(eid)
            if ev is None:
                continue
            src = orch.repos.sources.get(ev.source_id)
            chain.append({"evidence_id": eid, "quote": ev.quote,
                          "tier": ev.source_tier, "status": ev.status.value
                          if hasattr(ev.status, "value") else str(ev.status),
                          "url": ev.source_url,
                          "source_title": src.title if src else ""})
        return chain

    def list_gaps(self, project_id: str, offset=0, limit=50) -> dict:
        orch = _orch(self.ctx, project_id)
        items = []
        for g in sorted(orch.repos.gaps.all(project_id),
                        key=lambda x: -x.importance):
            d = json.loads(g.model_dump_json())
            d["category"] = g.category.value if hasattr(g.category, "value") \
                else str(g.category)
            items.append(d)
        return {"items": items[offset:offset + limit], "total": len(items),
                "offset": offset, "limit": limit}

    def contradictions(self, project_id: str) -> list[dict]:
        orch = _orch(self.ctx, project_id)
        return [json.loads(c.model_dump_json())
                for c in orch.repos.contradictions.all(project_id)]


class HypothesisService:
    def __init__(self, ctx):
        self.ctx = ctx

    def list_hypotheses(self, project_id: str, objective: str = "balanced") -> list[dict]:
        from research_engine.reasoning.hypothesis_engine import rank_hypotheses
        orch = _orch(self.ctx, project_id)
        rr = _rrepos(orch)
        ranked = rank_hypotheses(orch.repos, rr, project_id, objective)
        out = []
        for r in ranked:
            h = rr.hypotheses.get(r["id"])
            if h is None:
                continue
            d = json.loads(h.model_dump_json())
            d["rank_score"] = round(r["score"], 3)
            out.append(d)
        return out

    def get_hypothesis(self, project_id: str, hyp_id: str) -> dict:
        orch = _orch(self.ctx, project_id)
        h = _rrepos(orch).hypotheses.get(hyp_id)
        if h is None:
            raise NotFoundError("hypothesis", hyp_id)
        return json.loads(h.model_dump_json())

    def design_methodology(self, project_id: str, hypothesis_id: str) -> list[dict]:
        """Canonical methodology-design path (used by CLI and MCP; P0-05/BUG-06)."""
        from research_engine.reasoning.methodology_designer import MethodologyDesigner
        orch = _orch(self.ctx, project_id)
        rr = _rrepos(orch)
        h = rr.hypotheses.get(hypothesis_id)
        if h is None:
            raise NotFoundError("hypothesis", hypothesis_id)
        designs = MethodologyDesigner(orch.repos, rr,
                                      orch.router.reasoning).design(project_id, h)
        return [json.loads(d.model_dump_json()) for d in designs]

    def generate(self, project_id: str) -> dict:
        """Run hypothesis generation on demand (competing sets, spec #8)."""
        from research_engine.core.orchestrator import Orchestrator
        from research_engine.reasoning.pipeline import ReasoningPipeline
        orch = Orchestrator.load(self.ctx.cfg, project_id)
        pipe = ReasoningPipeline(orch.repos, _rrepos(orch),
                                 orch.router.reasoning, orch.registry)
        summary = pipe.run_for_project(project_id, mode=orch.project.mode)
        self.ctx.bus.publish(DomainEvent(
            "HypothesisCreated", project_id=project_id,
            payload={"count": len(summary.get("generated", []))}))
        return summary

    def history(self, project_id: str, hyp_id: str) -> list[dict]:
        orch = _orch(self.ctx, project_id)
        versions = _rrepos(orch).hypothesis_versions.for_hypothesis(hyp_id)
        return [{"version": v.version, "change_reason": v.change_reason,
                 "confidence_delta": v.confidence_delta,
                 "created_at": v.created_at}
                for v in versions]


class ReportService:
    def __init__(self, ctx):
        self.ctx = ctx

    def list_reports(self, project_id: str) -> list[str]:
        path = Path(self.ctx.data_dir, project_id, "reports")
        return sorted(f.name for f in path.glob("*.md")) if path.exists() else []

    def read_report(self, project_id: str, name: str) -> str:
        if "/" in name or ".." in name:   # path traversal guard (#146)
            raise NotFoundError("report", name)
        p = Path(self.ctx.data_dir, project_id, "reports", name)
        if not p.exists():
            raise NotFoundError("report", name)
        return p.read_text(encoding="utf-8")

    def regenerate_async(self, project_id: str) -> str:
        job = ResearchJobFactory.report_job(self.ctx, project_id)
        return job.id

    def versions(self, project_id: str, name: str) -> list[dict]:
        """Report version history (spec #85): derived from snapshot registry."""
        from research_engine.memory.snapshots import SnapshotStore
        orch = _orch(self.ctx, project_id)
        store = SnapshotStore(orch.ws.root)
        snaps = store.list()
        return [{"snapshot_id": s["id"], "created_at": s.get("created_at", ""),
                 "evidence_count": s.get("counts", {}).get("evidence")}
                for s in snaps]


class ResearchJobFactory:
    """Builds standard platform jobs."""

    @staticmethod
    def report_job(ctx, project_id: str):
        job = ResearchJobFactory._new_job(project_id, "report",
                                          JobPriority.LOW)
        task = JobTask(job_id=job.id, project_id=project_id,
                       type="REGENERATE_REPORT",
                       resource_profile=ResourceProfile.CPU_LIGHT,
                       payload={"project_id": project_id})
        ctx.scheduler.submit_job(job, [task])
        ctx.start_scheduler()
        return job

    @staticmethod
    def experiment_job(ctx, project_id: str, experiment_id: str,
                       priority: int = JobPriority.HIGH):
        job = ResearchJobFactory._new_job(project_id, "experiment", priority)
        task = JobTask(job_id=job.id, project_id=project_id,
                       type="RUN_EXPERIMENT",
                       resource_profile=ResourceProfile.EXPERIMENT_HEAVY,
                       priority=priority,
                       payload={"project_id": project_id,
                                "experiment_id": experiment_id})
        ctx.scheduler.submit_job(job, [task])
        ctx.start_scheduler()
        return job

    @staticmethod
    def watcher_tick_job(ctx, watcher_id: str, project_id: str):
        job = ResearchJobFactory._new_job(project_id, "watcher_tick",
                                          JobPriority.BACKGROUND)
        task = JobTask(job_id=job.id, project_id=project_id,
                       type="WATCHER_TICK",
                       resource_profile=ResourceProfile.NETWORK_LIGHT,
                       payload={"watcher_id": watcher_id,
                                "project_id": project_id})
        ctx.scheduler.submit_job(job, [task])
        return job

    @staticmethod
    def incremental_update_job(ctx, project_id: str):
        job = ResearchJobFactory._new_job(project_id, "incremental_update",
                                          JobPriority.NORMAL)
        task = JobTask(job_id=job.id, project_id=project_id,
                       type="INCREMENTAL_UPDATE",
                       resource_profile=ResourceProfile.NETWORK_LIGHT,
                       payload={"project_id": project_id})
        ctx.scheduler.submit_job(job, [task])
        ctx.start_scheduler()
        return job

    @staticmethod
    def _new_job(project_id: str, jtype: str, priority: int) -> object:
        from research_engine.models.job import ResearchJob as RJ
        return RJ(project_id=project_id, type=jtype, priority=priority)


class ExperimentService:
    def approve(self, project_id: str, experiment_id: str, approved: bool,
                note: str = "") -> dict:
        """Canonical human-approval gate (P0-11): CLI/MCP/API all route here."""
        from research_engine.reasoning.result_ingestion import approve_experiment
        orch = _orch(self.ctx, project_id)
        rr = _rrepos(orch)
        updated = approve_experiment(rr, project_id, experiment_id,
                                     approved=approved, note=note)
        return json.loads(updated.model_dump_json())
    def __init__(self, ctx):
        self.ctx = ctx

    def register(self, project_id: str, spec: dict) -> dict:
        """Register an experiment against a hypothesis + methodology (spec #35)."""
        from research_engine.models.reasoning import Experiment
        orch = _orch(self.ctx, project_id)
        exp = Experiment(project_id=project_id,
                         hypothesis_id=spec.get("hypothesis_id", ""),
                         methodology_id=spec.get("methodology_id", ""),
                         title=spec.get("title", "experiment"))
        if spec.get("configuration"):
            exp.decision_note = json.dumps(spec["configuration"])[:500]
        # registration requires human gate per Phase 3 lifecycle (spec #34/#45)
        if spec.get("risk_level"):
            exp.risk_level = spec["risk_level"]
        exp.status = "READY_FOR_HUMAN_APPROVAL"
        exp.ensure_id()
        rr = _rrepos(orch)
        rr.experiments.save(exp)
        self.ctx.bus.publish(DomainEvent("ExperimentRegistered",
                                         project_id=project_id,
                                         payload={"experiment_id": exp.id}))
        return json.loads(exp.model_dump_json())

    def execute(self, project_id: str, experiment_id: str) -> dict:
        """Queue execution as a platform job; sandbox enforced at run time."""
        orch = _orch(self.ctx, project_id)
        rr = _rrepos(orch)
        exp = rr.experiments.get(experiment_id)
        if exp is None:
            raise NotFoundError("experiment", experiment_id)
        job = ResearchJobFactory.experiment_job(self.ctx, project_id,
                                                experiment_id)
        return {"job_id": job.id, "experiment_id": experiment_id,
                "status": "QUEUED"}

    def compare(self, project_id: str, exp_a: str, exp_b: str) -> dict:
        """Experiment comparison incl. comparability verdict (spec #41)."""
        from research_engine.experiments.compare import compare_experiments
        orch = _orch(self.ctx, project_id)
        return compare_experiments(_rrepos(orch), exp_a, exp_b)

    def add_result(self, project_id: str, experiment_id: str,
                   observations: list[str] | None = None,
                   metrics: dict | None = None,
                   raw_notes: str = "") -> dict:
        """Manual result ingestion with pre-registered criteria verdicts."""
        from research_engine.reasoning.result_ingestion import ResultIngestor
        orch = _orch(self.ctx, project_id)
        ing = ResultIngestor(orch.repos, _rrepos(orch))
        outcome = ing.ingest(project_id, experiment_id,
                             observations=observations or [],
                             metrics=metrics or {},
                             raw_notes=raw_notes)
        self.ctx.bus.publish(DomainEvent("ExperimentResultAvailable",
                                         project_id=project_id,
                                         payload={"experiment_id": experiment_id,
                                                  "verdict":
                                                  outcome.get("verdict", "")}))
        return outcome
