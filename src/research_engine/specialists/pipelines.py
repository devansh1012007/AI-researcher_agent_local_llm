"""Shared pipeline helpers for builtin domain specialists (Phase 5 §32–33).

Stage discipline: every specialist records its stages (name, inputs used,
notes, duration) into output.artifacts["stages"] so synthesis and the user
provenance view can show WHAT each specialist contributed (§70/§81).
"""
from __future__ import annotations

import time
from typing import Callable


class StageTracker:
    def __init__(self) -> None:
        self.stages: list[dict] = []

    def run(self, name: str, fn: Callable[[], dict]) -> dict:
        t0 = time.monotonic()
        out = fn() or {}
        self.stages.append({
            "stage": name,
            "seconds": round(time.monotonic() - t0, 3),
            **{k: v for k, v in out.items()
               if k in ("inputs", "produced", "note")},
        })
        return out


def keyword_hits(text: str, terms: list[str]) -> list[str]:
    t = (text or "").lower()
    return [k for k in terms if k in t]


CONSTRAINT_CATEGORIES = {
    "hardware": ["gpu", "sensor", "actuator", "robot", "hardware",
                 "memory", "ram", "camera"],
    "software": ["library", "framework", "sdk", "api", "license",
                 "open-source", "dependency"],
    "integration": ["integrat", "compatib", "migration", "workflow",
                    "existing system", "erp", "pipeline"],
    "deployment": ["deploy", "cloud", "on-premise", "edge", "latency",
                   "uptime", "scalab"],
    "performance": ["throughput", "accuracy", "latency", "benchmark",
                    "fps", "ms ", "speedup"],
    "cost": ["cost", "price per", "$", "budget", "spend", "expensive"],
}

TREND_LEXICON = [
    "new model", "release", "open-sourced", "open-source model",
    "benchmark jump", "cost curve", "price drop", "cut costs",
    "reduced cost", "cheaper", "regulation", "compliance requirement",
    "platform shift", "adoption", "breakthrough", "api now supports",
]

ENABLING_TREND_TERMS = [
    "cost curve", "price drop", "cut costs", "reduced cost", "cheaper",
    "breakthrough", "adoption", "open-source model", "open-sourced",
]


def feasibility_confidence(covered: set[str], total: set[str]) -> float:
    """Deterministic coverage-based confidence — never an opaque number."""
    if not total:
        return 0.0
    return round(len(covered & total) / len(total), 3)
