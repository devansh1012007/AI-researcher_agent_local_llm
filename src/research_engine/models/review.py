"""Review decisions: an append-only, human-labelled overlay on claims,
contradictions and validation plans.

A review decision is an overlay row: it never rewrites machine-owned state
(INV-005 "REJECTED" = verification failed is distinct from "human rejected").
Rows are keyed by a content hash of the target so a decision whose target was
later edited is detected as *stale* — surfaced, never auto-applied. Among
non-stale decisions the latest wins.

Fields:
    target_kind   - claim | contradiction | validation_plan
    target_id     - id of the reviewed entity
    verdict       - one of the kind's verdict vocabulary
    note          - free-text analyst note
    reviewer_label- free-text label of who recorded the decision
    actor_kind    - os_user (CLI) | unverified_label (API/MCP loopback)
    decided_at    - ISO-8601 UTC timestamp
    content_hash  - sha256 of the normalised target content at decision time
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import ClassVar

from pydantic import Field

from research_engine.models.base import Entity


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(s: str) -> str:
    """Normalise text for content hashing: collapse whitespace, lowercase."""
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def content_hash_for(target_kind: str, **fields: str) -> str:
    """Content hash of a review target, per D.5.

    - claim:           sha256(norm(claim_text))
    - contradiction:   sha256(norm(statement_a) + "\\x00" + norm(statement_b))
    - validation_plan: sha256(norm(assumption) + "\\x00" + norm(cheapest_test))
    """
    if target_kind == "claim":
        payload = _norm(fields["claim_text"])
    elif target_kind == "contradiction":
        payload = _norm(fields["statement_a"]) + "\x00" + _norm(fields["statement_b"])
    elif target_kind == "validation_plan":
        payload = _norm(fields["assumption"]) + "\x00" + _norm(fields["cheapest_test"])
    else:
        raise ValueError(f"Unknown review target_kind: {target_kind!r}")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Verdict state machine (D.5, mirrors reasoning/hypothesis_engine.py:32-50)
# ---------------------------------------------------------------------------

REVIEW_VERDICTS: dict[str, frozenset[str]] = {
    "claim": frozenset({"APPROVED", "REJECTED"}),
    "contradiction": frozenset({"CONFIRMED", "DISMISSED"}),
    "validation_plan": frozenset({"ACCEPTED", "REVISION_REQUESTED"}),
}

# Latest non-stale decision wins, so any in-vocabulary verdict is reachable
# from any prior state (including none). A verdict outside the kind's
# vocabulary is an illegal transition and raises loudly.
ALLOWED_REVIEW_TRANSITIONS: dict[str, dict[str, frozenset[str]]] = {
    kind: {"": verdicts, **{v: verdicts for v in verdicts}}
    for kind, verdicts in REVIEW_VERDICTS.items()
}


class IllegalReviewTransition(ValueError):
    """Raised when a verdict is not in the vocabulary for the target kind."""


class ReviewDecision(Entity):
    """One analyst review decision. Append-only overlay row (prefix `rev`)."""
    PREFIX: ClassVar[str] = "rev"

    target_kind: str = ""          # claim | contradiction | validation_plan
    target_id: str = ""
    verdict: str = ""
    note: str = ""
    reviewer_label: str = ""
    actor_kind: str = ""           # os_user | unverified_label
    decided_at: str = ""           # ISO-8601 UTC
    content_hash: str = ""
