"""Review service: the single authoritative path for analyst review decisions
(C14).

`record_decision`, `list_decisions` and `apply_validation_plan_revision` live
here; the CLI/API/MCP adapters are thin wrappers (C15). Overlay only: machine
state is never rewritten. A decision whose `content_hash` no longer matches
its target is *stale* — surfaced, never auto-applied. Among non-stale
decisions the latest wins.

The verdict state machine mirrors `reasoning/hypothesis_engine.py:32-50`:
each target kind has a closed verdict vocabulary; a verdict outside it is an
illegal transition and raises loudly.
"""
from __future__ import annotations

import json

from research_engine.models.review import (
    ReviewDecision,
    IllegalReviewTransition,
    content_hash_for,
    REVIEW_VERDICTS,
    ALLOWED_REVIEW_TRANSITIONS,
    utcnow_iso,
)
from research_engine.services.research_service import NotFoundError


def _target_fields(target_kind: str, target) -> dict:
    if target_kind == "claim":
        return {"claim_text": getattr(target, "text", "")}
    if target_kind == "contradiction":
        return {
            "statement_a": getattr(target, "statement_a", ""),
            "statement_b": getattr(target, "statement_b", ""),
        }
    if target_kind == "validation_plan":
        return {
            "assumption": getattr(target, "assumption", ""),
            "cheapest_test": getattr(target, "cheapest_test", ""),
        }
    raise IllegalReviewTransition(f"Unknown review target_kind: {target_kind!r}")


class ReviewService:
    def __init__(self, ctx):
        self.ctx = ctx

    # ------------------------------------------------------------------ internals
    def _orch(self, project_id: str):
        from research_engine.core.orchestrator import Orchestrator
        try:
            return Orchestrator.load(self.ctx.cfg, project_id)
        except FileNotFoundError as exc:
            raise NotFoundError("project", project_id) from exc

    def _review_decision_repo(self, orch):
        from research_engine.storage.review_repos import ReviewDecisionsRepos
        if not hasattr(orch, "_review_repos"):
            orch._review_repos = ReviewDecisionsRepos(orch.db)
        return orch._review_repos.review_decisions

    def _load_target(self, orch, target_kind: str, target_id: str):
        """Fetch the reviewed entity so its content hash can be computed and
        its project_id verified (INV-013 isolation)."""
        if target_kind == "claim":
            return orch.repos.claims.get(target_id)
        if target_kind == "contradiction":
            return orch.repos.contradictions.get(target_id)
        if target_kind == "validation_plan":
            from research_engine.specialists.startup.repos import get_startup_repos
            return get_startup_repos(orch).falsification_tests.get(target_id)
        raise IllegalReviewTransition(f"Unknown review target_kind: {target_kind!r}")

    @staticmethod
    def _current_verdict(repo, project_id: str, target_kind: str,
                         target_id: str, content_hash: str) -> str | None:
        """Verdict of the latest NON-STALE decision for a target, else None."""
        live = [
            d for d in repo.for_target(project_id, target_kind, target_id)
            if d.content_hash == content_hash
        ]
        if not live:
            return None
        return max(live, key=lambda d: d.decided_at).verdict

    # ------------------------------------------------------------------ public API
    def record_decision(self, project_id: str, target_kind: str, target_id: str,
                        verdict: str, note: str = "",
                        reviewer_label: str = "",
                        actor_kind: str = "unverified_label") -> dict:
        """Record (or re-affirm) a review decision.

        Illegal verdicts for the target kind raise `IllegalReviewTransition`
        loudly. Re-affirming the current verdict is a no-op. The new row is
        stamped with the target's current content hash; a later edit to the
        target makes it stale (surfaced by `list_decisions`, never applied).
        """
        if target_kind not in ALLOWED_REVIEW_TRANSITIONS:
            raise IllegalReviewTransition(
                f"Unknown review target_kind: {target_kind!r}")
        if verdict not in REVIEW_VERDICTS.get(target_kind, frozenset()):
            raise IllegalReviewTransition(
                f"Illegal {target_kind} verdict {verdict!r}; "
                f"allowed: {sorted(REVIEW_VERDICTS[target_kind])}")

        orch = self._orch(project_id)
        repo = self._review_decision_repo(orch)
        target = self._load_target(orch, target_kind, target_id)
        if target is None or getattr(target, "project_id", "") != project_id:
            raise NotFoundError(target_kind, target_id)

        content_hash = content_hash_for(target_kind,
                                        **_target_fields(target_kind, target))
        current = self._current_verdict(repo, project_id, target_kind,
                                          target_id, content_hash)
        if current == verdict:
            # Re-affirming the current verdict: nothing changes (latest wins).
            current_row = self._latest_row(repo, project_id, target_kind,
                                           target_id, content_hash)
            return json.loads(current_row.model_dump_json()) if current_row else {}

        decision = ReviewDecision(
            project_id=project_id,
            target_kind=target_kind,
            target_id=target_id,
            verdict=verdict,
            note=note,
            reviewer_label=reviewer_label,
            actor_kind=actor_kind,
            decided_at=utcnow_iso(),
            content_hash=content_hash,
        )
        decision.ensure_id()
        repo.save(decision)
        return json.loads(decision.model_dump_json())

    def list_decisions(self, project_id: str, target_kind: str | None = None,
                       target_id: str | None = None) -> list[dict]:
        """List review decisions for a project, annotated with staleness.

        A decision is stale when its `content_hash` no longer matches the
        target's current content — it is surfaced (`is_stale=True`) but never
        applied, and never displaces a live decision.
        """
        orch = self._orch(project_id)
        repo = self._review_decision_repo(orch)
        decisions = repo.all(project_id)
        if target_kind:
            decisions = [d for d in decisions if d.target_kind == target_kind]
        if target_id:
            decisions = [d for d in decisions if d.target_id == target_id]

        out = []
        for d in decisions:
            target = self._load_target(orch, d.target_kind, d.target_id)
            current_hash = (
                content_hash_for(d.target_kind,
                                 **_target_fields(d.target_kind, target))
                if target is not None else None
            )
            is_stale = (current_hash is None) or (d.content_hash != current_hash)
            item = json.loads(d.model_dump_json())
            item["is_stale"] = is_stale
            out.append(item)
        out.sort(key=lambda d: d.get("decided_at", ""))
        return out

    def apply_validation_plan_revision(self, project_id: str,
                                       validation_plan_id: str, note: str = "",
                                       reviewer_label: str = "",
                                       actor_kind: str = "unverified_label") -> dict:
        """Ask for a revision of a validation plan: record a
        `validation_plan` / `REVISION_REQUESTED` decision (overlay only — the
        plan itself is never rewritten here)."""
        return self.record_decision(
            project_id, "validation_plan", validation_plan_id,
            "REVISION_REQUESTED", note, reviewer_label, actor_kind)

    # ------------------------------------------------------------------ helpers
    def _latest_row(self, repo, project_id: str, target_kind: str,
                    target_id: str, content_hash: str) -> ReviewDecision | None:
        live = [
            d for d in repo.for_target(project_id, target_kind, target_id)
            if d.content_hash == content_hash
        ]
        return max(live, key=lambda d: d.decided_at) if live else None

    def current_verdict(self, project_id: str, target_kind: str,
                        target_id: str) -> str | None:
        """Current (latest non-stale) verdict for a target, or None."""
        orch = self._orch(project_id)
        repo = self._review_decision_repo(orch)
        target = self._load_target(orch, target_kind, target_id)
        if target is None:
            return None
        content_hash = content_hash_for(target_kind,
                                        **_target_fields(target_kind, target))
        return self._current_verdict(repo, project_id, target_kind, target_id,
                                     content_hash)
