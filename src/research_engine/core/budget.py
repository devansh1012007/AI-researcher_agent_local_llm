"""Live budget tracking with hard enforcement."""
from __future__ import annotations

import logging
import time

from research_engine.core.config import AppConfig
from research_engine.models.project import ResearchProject

log = logging.getLogger(__name__)


class Budget:
    def __init__(self, cfg: AppConfig, project: ResearchProject, wall_clock_start: float | None = None):
        self.cfg = cfg
        self.p = project
        self.started = wall_clock_start if wall_clock_start is not None else time.time()

    @property
    def usage(self):
        return self.p.budget

    # -- checks -------------------------------------------------------------
    def queries_left(self) -> int:
        return max(0, self.cfg.research.max_queries_per_iteration * (self.cfg.research.max_iterations + 1)
                   - self.usage.queries_used)

    def documents_left(self) -> int:
        return max(0, self.cfg.research.max_documents - self.usage.documents_used)

    def llm_calls_left(self) -> int:
        return max(0, self.cfg.research.max_llm_calls - self.usage.llm_calls_used)

    def iterations_left(self) -> int:
        return max(0, self.cfg.research.max_iterations - self.usage.iterations_used)

    def minutes_elapsed(self) -> float:
        return (time.time() - self.started) / 60.0

    def exhausted(self) -> str | None:
        """Return the first exhausted budget dimension, else None."""
        if self.queries_left() <= 0:
            return "queries"
        if self.documents_left() <= 0:
            return "documents"
        if self.llm_calls_left() <= 0:
            return "llm_calls"
        if self.minutes_elapsed() > self.cfg.research.max_wall_clock_minutes:
            return "wall_clock"
        return None

    # -- mutations ------------------------------------------------------------
    def spend_query(self, n: int = 1) -> None:
        self.usage.queries_used += n

    def spend_document(self, n: int = 1) -> None:
        self.usage.documents_used += n

    def spend_llm(self, n: int = 1) -> None:
        self.usage.llm_calls_used += n

    def spend_bytes(self, n: int) -> None:
        self.usage.bytes_downloaded += n

    def snapshot(self) -> dict:
        return {
            "queries": f"{self.usage.queries_used}/{self.cfg.research.max_queries_per_iteration}x{self.cfg.research.max_iterations}",
            "documents": f"{self.usage.documents_used}/{self.cfg.research.max_documents}",
            "llm_calls": f"{self.usage.llm_calls_used}/{self.cfg.research.max_llm_calls}",
            "iterations": f"{self.usage.iterations_used}/{self.cfg.research.max_iterations}",
            "minutes_elapsed": round(self.minutes_elapsed(), 1),
        }
