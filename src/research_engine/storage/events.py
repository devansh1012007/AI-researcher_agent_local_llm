"""Append-only structured event stream (JSONL) — the research audit trail.

Every major action is recorded here AND in the human-readable research_log.md.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


class EventLog:
    def __init__(self, project_dir: Path):
        self.path = project_dir / "events.jsonl"
        self.md_path = project_dir / "reports" / "research_log.md"
        self._lock = threading.Lock()
        self.md_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, project_id: str, event: str, component: str,
               task_id: str = "", duration_ms: float = 0.0,
               status: str = "ok", metadata: dict | None = None,
               error: str = "", human_line: str = "") -> dict:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "project_id": project_id,
            "event": event,
            "component": component,
            "task_id": task_id,
            "duration_ms": round(duration_ms, 1),
            "status": status,
            "metadata": metadata or {},
            "error": error,
        }
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
            if human_line:
                with self.md_path.open("a", encoding="utf-8") as f:
                    f.write(human_line + "\n")
        return entry

    def read_events(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
