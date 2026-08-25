"""Structured JSONL logging + secret redaction (spec #47/#66).

Every record: ts, level, component, event, project_id, job_id, task_id,
trace_id, duration, status, error. Correlation via trace_id.

Secrets (API keys, bearer tokens) are redacted before anything is written —
a log file must never become a credential leak.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_REDACT_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[=:]\s*\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"sk-[A-Za-z0-9]{8,}"),
]
_REDACTED = "<redacted>"


def redact(text: str) -> str:
    if not text:
        return text
    out = text
    for pat in _REDACT_PATTERNS:
        out = pat.sub(lambda m: m.group(0).split("=")[0].split(":")[0] + "=" + _REDACTED
                      if ("=" in m.group(0) or ":" in m.group(0)) else _REDACTED, out)
    return out


def new_trace_id() -> str:
    return "trc_" + uuid.uuid4().hex[:12]


class StructuredLogger:
    """Appends one JSON object per line. Cheap, lock-guarded, never throws."""

    def __init__(self, path: str | Path | None = None,
                 default_fields: dict | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._defaults = default_fields or {}
        self._console_echo = False  # tests/dev can enable

    def bind(self, **fields) -> "StructuredLogger":
        child = StructuredLogger(self.path, {**self._defaults, **fields})
        child._lock = self._lock
        return child

    def log(self, level: str, event: str, *, project_id: str = "", job_id: str = "",
            task_id: str = "", trace_id: str = "", duration_ms: float = 0.0,
            status: str = "ok", error: str = "", metadata: dict | None = None) -> dict:
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "event": event,
            "component": self._defaults.get("component", ""),
            "project_id": project_id or self._defaults.get("project_id", ""),
            "job_id": job_id or self._defaults.get("job_id", ""),
            "task_id": task_id or self._defaults.get("task_id", ""),
            "trace_id": trace_id or self._defaults.get("trace_id", ""),
            "duration_ms": round(duration_ms, 1),
            "status": status,
            "error": redact(error)[:500],
            "metadata": _deep_redact(metadata or {}),
        }
        if self.path is not None:
            line = json.dumps(rec, default=str)
            try:
                with self._lock:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with self.path.open("a", encoding="utf-8") as f:
                        f.write(line + "\n")
            except OSError:
                pass  # logging must never crash research
        return rec

    def info(self, event: str, **kw) -> dict:
        return self.log("info", event, **kw)

    def warn(self, event: str, **kw) -> dict:
        return self.log("warn", event, **kw)

    def error(self, event: str, error: str = "", **kw) -> dict:
        kw.setdefault("status", "error")
        return self.log("error", event, error=error, **kw)


def _deep_redact(obj):
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: ("<redacted>" if any(s in k.lower() for s in
                                      ("key", "secret", "token", "password"))
                    else _deep_redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_redact(x) for x in obj]
    return obj


_platform_logger: StructuredLogger | None = None


def platform_logger(data_dir: str | Path | None = None) -> StructuredLogger:
    """Process-wide structured logger writing under <data_dir>/_global/logs/."""
    global _platform_logger
    if data_dir is not None or _platform_logger is None:
        path = None
        if data_dir is not None:
            path = Path(data_dir) / "_global" / "logs" / "platform.jsonl"
        _platform_logger = StructuredLogger(path, {"component": "platform"})
    return _platform_logger


class IncidentLog:
    """Human-readable incident log for significant failures (spec #124)."""

    def __init__(self, data_dir: str | Path):
        self.path = Path(data_dir) / "_global" / "incidents.md"

    def record(self, job_id: str, component: str, symptom: str,
               cause: str, resolution: str = "") -> None:
        from datetime import datetime as dt
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = (f"\n## {dt.now().strftime('%Y-%m-%d %H:%M:%S')} — {component}\n"
                 f"- Job: {job_id or 'n/a'}\n- Symptom: {symptom}\n"
                 f"- Cause: {cause}\n- Resolution: {resolution or 'open'}\n")
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(entry)
        except OSError:
            pass
