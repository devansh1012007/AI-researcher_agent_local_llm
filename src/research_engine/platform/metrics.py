"""Metrics registry + resource telemetry (spec #48/#82/#147).

Thread-safe in-memory counters/gauges/histograms with periodic snapshots to
JSONL. Resource sampling reads /proc on Linux and degrades gracefully
elsewhere — never crashes the research loop over telemetry.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Histogram:
    """Bounded reservoir (simple: keep all if < 2048, else ring)."""

    __slots__ = ("_values", "_lock", "_sum", "_count")

    def __init__(self):
        self._values: list[float] = []
        self._lock = threading.Lock()
        self._sum = 0.0
        self._count = 0

    def observe(self, v: float) -> None:
        with self._lock:
            self._count += 1
            self._sum += v
            self._values.append(v)
            if len(self._values) > 2048:
                self._values = self._values[-1024:]

    def snapshot(self) -> dict:
        with self._lock:
            vals = sorted(self._values)
            n = len(vals)

            def pct(p):
                return round(vals[min(n - 1, int(n * p))], 4) if n else None

            return {"count": self._count,
                    "mean": round(self._sum / max(1, self._count), 4),
                    "p50": pct(0.50), "p95": pct(0.95), "p99": pct(0.99)}


class MetricsRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self.counters: dict[str, float] = defaultdict(float)
        self.gauges: dict[str, float] = {}
        self.histograms: dict[str, Histogram] = defaultdict(Histogram)
        self.labels: dict[str, dict] = {}

    # -- recording ---------------------------------------------------------
    def incr(self, name: str, by: float = 1.0, **labels) -> None:
        key = self._key(name, labels)
        with self._lock:
            self.counters[key] += by
            if labels:
                self.labels[key] = labels

    def gauge(self, name: str, value: float, **labels) -> None:
        key = self._key(name, labels)
        with self._lock:
            self.gauges[key] = value
            if labels:
                self.labels[key] = labels

    def observe(self, name: str, value: float, **labels) -> None:
        self.histograms[self._key(name, labels)].observe(value)

    @staticmethod
    def _key(name: str, labels: dict) -> str:
        if not labels:
            return name
        tag = ",".join(f"{k}={labels[k]}" for k in sorted(labels))
        return f"{name}{{{tag}}}"

    # -- export ------------------------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            return {
                "ts": _now(),
                "counters": dict(self.counters),
                "gauges": dict(self.gauges),
                "histograms": {k: h.snapshot() for k, h in self.histograms.items()},
            }

    def dump(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.snapshot(), indent=2))
        return path


class GlobalMetrics:
    """Process-wide registry so any component can record without wiring."""
    _instance: "GlobalMetrics | None" = None
    _inst_lock = threading.Lock()

    def __init__(self):
        self.registry = MetricsRegistry()
        self._sink: Path | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @classmethod
    def get(cls) -> "GlobalMetrics":
        with cls._inst_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def start_sink(self, data_dir: str | Path, interval_s: float = 30.0) -> None:
        self._sink = Path(data_dir) / "_global" / "metrics.jsonl"
        self._sink.parent.mkdir(parents=True, exist_ok=True)
        if self._thread and self._thread.is_alive():
            return

        def _loop():
            while not self._stop.wait(interval_s):
                try:
                    with self._sink.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(
                            {**self.registry.snapshot(),
                             "resources": sample_resources()}, default=str) + "\n")
                except Exception:
                    pass  # telemetry must never take the platform down

        self._thread = threading.Thread(target=_loop, name="metrics-sink", daemon=True)
        self._thread.start()

    def stop_sink(self) -> None:
        self._stop.set()


# ---------------------------------------------------------------- resources
def sample_resources() -> dict:
    """CPU/RAM/disk snapshot. /proc-based; returns {} on unsupported systems."""
    out: dict = {}
    try:
        load1, load5, load15 = os.getloadavg()
        out["load"] = [round(load1, 2), round(load5, 2), round(load15, 2)]
    except (OSError, AttributeError):
        pass
    mem = _read_meminfo()
    if mem:
        out["mem"] = mem
    cpu = _read_proc_stat()
    if cpu is not None:
        out["cpu_busy_pct"] = cpu
    disk = _read_disk()
    if disk:
        out["disk"] = disk
    return out


def _read_meminfo() -> dict | None:
    try:
        info: dict[str, int] = {}
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    info[parts[0].strip()] = int(parts[1].strip().split()[0])  # kB
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", 0)
        if not total:
            return None
        return {"total_mb": total // 1024, "available_mb": avail // 1024,
                "used_pct": round(100 * (total - avail) / total, 1)}
    except (OSError, ValueError, IndexError):
        return None


_prev_cpu: list[int] | None = None


def _read_proc_stat() -> float | None:
    global _prev_cpu
    try:
        with open("/proc/stat", encoding="ascii") as f:
            first = f.readline().split()[1:]
        vals = [int(x) for x in first[:8]]
        idle = vals[3] + vals[4]
        total = sum(vals)
        global_sample = (idle, total)
    except (OSError, ValueError, IndexError):
        return None
    prev = _prev_cpu
    globals()["_prev_cpu"] = [idle, total]
    if prev is None:
        return None
    d_idle = idle - prev[0]
    d_total = total - prev[1]
    if d_total <= 0:
        return None
    return round(100 * (1 - d_idle / d_total), 1)


def _read_disk(path: str = ".") -> dict | None:
    import shutil
    try:
        usage = shutil.disk_usage(path)
        return {"free_gb": round(usage.free / 2**30, 1),
                "used_pct": round(100 * usage.used / usage.total, 1)}
    except OSError:
        return None
