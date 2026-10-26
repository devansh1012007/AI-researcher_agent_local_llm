"""Document and chunk models."""
from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from research_engine.models.base import Entity
from research_engine.models.enums import ContentStatus as ContentStatusStr


class Document(Entity):
    PREFIX: ClassVar[str] = "doc"

    source_id: str = ""
    url: str = ""
    title: str = ""
    raw_content_path: str = ""   # path to original artifact on disk
    text: str = ""               # cleaned normalized text
    content_hash: str = ""
    content_status: str = ContentStatusStr.FETCHED.value
    content_type: str = ""       # html | pdf | text | json
    page_count: int = 0
    word_count: int = 0
    error: str = ""

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)


class DocumentChunk(Entity):
    PREFIX: ClassVar[str] = "chk"

    document_id: str = ""
    sequence: int = 0
    text: str = ""
    heading: str = ""
    page: int | None = None
    char_start: int = 0
    char_end: int = 0

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)
