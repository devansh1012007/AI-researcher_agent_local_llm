"""Quality & policy application service (Phase 6 §86, §52-§55, §85).

Single authoritative path for every interface (CLI/API/MCP) touching the
learning stores. Owns ALL writes (policy lifecycle, feedback, reviews,
alert status); interfaces never touch PlatformDB directly (INV-008).
Reads are cheap projections over platform.sqlite + project stores.
"""
from __future__ import annotations

from research_engine.adaptive.critic import critique_run
from research_engine.adaptive.drift import (
    diversity_report, policy_drift_report, specialist_drift_report)
from research_engine.adaptive.model_policy import assess_models
from research_engine.adaptive.policies import PolicyRegistry
from research_engine.services.context import ServiceContext


class QualityService:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx
        self.registry = PolicyRegistry(ctx.platform_db)

    # ------------------------------------------------------------ dashboard
    def dashboard(self, project_id: str = "") -> dict:
        db = self.ctx.platform_db
        outcomes = db.list_outcomes(project_id, limit=50)
        agg = {
            "runs": len(outcomes),
            "avg_gain": round(sum(
                o["data"].get("research_gain", {}).get("research_gain_v2", 0)
                for o in outcomes) / max(1, len(outcomes)), 4),
            "avg_grounded_ratio": round(sum(
                o["data"].get("quality_metrics", {})
                .get("claim_grounded_ratio", 0) for o in outcomes)
                / max(1, len(outcomes)), 4),
        }
        specialists = []
        for row in db.list_specialist_perf():
            runs = row["runs"] or 0
            specialists.append({
                "specialist": row["specialist"], "version": row["version"],
                "task_type": row["task_type"], "runs": runs,
                "failure_rate": round(row["failures"] / runs, 3) if runs else None,
                "avg_latency_s": row["avg_latency_s"],
            })
        return {
            "project_id": project_id,
            "outcomes_summary": agg,
            "specialists": sorted(specialists,
                                  key=lambda s: -s["runs"])[:20],
            "models": assess_models(db),
            "query_families": sorted(
                db.list_query_family_perf(),
                key=lambda r: -(r["avg_utility"] or 0)),
            "sources": db.list_source_perf(),
            "diversity": diversity_report(db),
            "policy_drift": policy_drift_report(db),
        }

    def specialist_detail(self, specialist_id: str) -> dict:
        return specialist_drift_report(self.ctx.platform_db, specialist_id)

    # -------------------------------------------------------------- policies
    def list_policies(self, kind: str = "") -> list[dict]:
        return self.registry.list(kind)

    def propose_policy(self, kind: str, version: str, body: dict,
                       evaluation: dict | None = None) -> dict:
        self.registry.propose(kind, version, body, evaluation=evaluation)
        return {"kind": kind, "version": version, "status": "draft"}

    def record_evaluation(self, kind: str, version: str,
                          evaluation: dict) -> dict:
        self.registry.record_evaluation(kind, version, evaluation)
        pol = self.ctx.platform_db.get_policy(kind, version)
        return {"kind": kind, "version": version,
                "evaluation": pol["evaluation"]}

    def activate_policy(self, kind: str, version: str,
                        reason: str = "") -> dict:
        self.registry.activate(kind, version, reason=reason)
        return {"kind": kind, "active_version":
                self.registry.active_version(kind)}

    def rollback_policy(self, kind: str, reason: str = "") -> dict:
        target = self.registry.rollback(kind, reason=reason)
        if target is None:
            target = "baseline"
            self.registry.deactivate(kind, reason=reason or "rollback")
        return {"kind": kind, "active_version": target}

    def compare_policies(self, kind: str, va: str, vb: str) -> dict:
        return self.registry.compare(kind, va, vb)

    # -------------------------------------------------------------- feedback
    def submit_feedback(self, project_id: str, target_kind: str,
                        target_id: str, verdict: str,
                        note: str = "") -> dict:
        import uuid
        fid = f"fb_{uuid.uuid4().hex[:12]}"
        self.ctx.platform_db.save_feedback(fid, project_id, target_kind,
                                           target_id, verdict, note)
        return {"feedback_id": fid}

    def list_feedback(self, project_id: str) -> list[dict]:
        return self.ctx.platform_db.list_feedback(project_id)

    # -------------------------------------------------------------- decisions
    def decisions(self, project_id: str, kind: str = "") -> list[dict]:
        return self.ctx.platform_db.list_decisions(project_id, kind=kind)

    def set_decision_gain(self, decision_id: str, actual_gain: float) -> None:
        self.ctx.platform_db.set_decision_actual_gain(decision_id,
                                                      float(actual_gain))

    # -------------------------------------------------------------- alerts
    def alerts(self, project_id: str, status: str = "open") -> list[dict]:
        return self.ctx.platform_db.list_alerts(project_id, status=status)

    def acknowledge_alert(self, alert_id: str) -> bool:
        return self.ctx.platform_db.update_alert_status(alert_id,
                                                        "acknowledged")

    # -------------------------------------------------------------- reviews
    def review(self, project_id: str, level: str = "STANDARD",
               llm=None, run_id: str = "") -> dict:
        from research_engine.core.orchestrator import Orchestrator
        orch = Orchestrator.load(self.ctx.cfg, project_id)
        rev = critique_run(orch, project_id, run_id=run_id, level=level,
                           llm=llm)
        self.ctx.platform_db.save_review(
            rev["review_id"], project_id, rev["run_id"],
            rev["dimensions"], rev["findings"],
            critic_backend=rev["critic_backend"],
            prompt_version=rev.get("prompt_version", ""))
        return rev

    def list_reviews(self, project_id: str) -> list[dict]:
        return self.ctx.platform_db.list_reviews(project_id)

    # -------------------------------------------------------------- outcomes
    def outcomes(self, project_id: str, limit: int = 10) -> list[dict]:
        return self.ctx.platform_db.list_outcomes(project_id, limit=limit)


def quality_service(ctx: ServiceContext | None = None) -> QualityService:
    from research_engine.services.context import get_context
    return QualityService(ctx or get_context())
