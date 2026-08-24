"""Base model with stable IDs, timestamps, provenance hooks."""
from __future__ import annotations

from datetime import datetime, timezone

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from research_engine.core.ids import next_id


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Entity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    PREFIX: ClassVar[str] = "ent"

    id: str = Field(default_factory=lambda: "")
    project_id: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def ensure_id(self, prefix: str | None = None) -> None:
        if not self.id:
            self.id = next_id(prefix or self.PREFIX)
        self.updated_at = utcnow()
