"""Typed repository for review decisions (C13).

`review_decisions` is an overlay table created by `storage/database.py`
`_EXTRA_TABLES` (`CREATE TABLE IF NOT EXISTS` on every init, no migration).
The repo owns its own `_index_cols`, declared both in the DDL and here, per
the per-repository convention (`storage/repositories.py:35`).
"""
from __future__ import annotations

from research_engine.models.review import ReviewDecision
from research_engine.storage.database import Database
from research_engine.storage.repositories import Repository, _enum_val


class ReviewDecisionRepo(Repository):
    table = "review_decisions"
    model = ReviewDecision

    def _index_cols(self, d: ReviewDecision):
        return {
            "target_kind": d.target_kind,
            "target_id": d.target_id,
            "verdict": d.verdict,
            "actor_kind": _enum_val(d.actor_kind),
            "content_hash": d.content_hash,
        }

    def for_target(self, project_id: str, target_kind: str,
                   target_id: str) -> list[ReviewDecision]:
        return self.all(
            project_id,
            "target_kind=? AND target_id=?",
            (target_kind, target_id),
        )


class ReviewDecisionsRepos:
    """Bundle for the review overlay, bound to one Database."""

    def __init__(self, db: Database):
        self.db = db
        self.review_decisions = ReviewDecisionRepo(db)
