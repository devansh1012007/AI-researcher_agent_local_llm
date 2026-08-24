"""Task abstraction for the local scheduler."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from research_engine.models.base import Entity, utcnow
from research_engine.models.enums import TaskStatus, TaskType


class Task(Entity):
    PREFIX: ClassVar[str] = "task"

    type: TaskType = TaskType.SEARCH
    priority: float = 0.5
    status: TaskStatus = TaskStatus.PENDING
    iteration: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    attempt_count: int = 0
    max_attempts: int = 3
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    error: str = ""

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)
