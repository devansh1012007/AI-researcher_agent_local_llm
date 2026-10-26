"""User clarification question model (Phase 5)."""
from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from research_engine.models.base import Entity


class QuestionStatus:
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"
    SKIPPED = "SKIPPED"
    DEFAULTED = "DEFAULTED"


class Question(Entity):
    """Structured question posed by the engine when critical inputs are ambiguous."""
    PREFIX: ClassVar[str] = "q"

    text: str = ""
    why_asking: str = ""
    changes: str = ""  # Quality gate (INV-032): must state what the answer changes in the plan/scope
    options: list[str] = Field(default_factory=list)
    default_assumption: str = ""
    blocking: bool = False
    status: str = QuestionStatus.OPEN
    answer: str = ""
    answered_at: str | None = None
    trigger_source: str = ""  # required_input | ambiguity | ask_user_when | conflicting_scope
    assumption_id: str = ""
    source_id: str = ""
    evidence_id: str = ""
    iteration: int = 0

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)
