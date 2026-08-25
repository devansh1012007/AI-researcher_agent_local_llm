"""Internal event bus + persistent event log (spec #21/#22/#74/#75).

Local, lightweight, thread-safe pub/sub. The interface is deliberately
broker-shaped (subscribe/publish) so a future Redis/NATS backend can slot in
without touching domain logic. Important events are ALSO persisted
append-only to the platform DB for audit/replay (spec #76).

Domain events carry: event_id, type, project_id, job_id, ts, payload.
"""
from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Canonical domain event types (spec #21/#74)
EVENT_TYPES = (
    "ResearchStarted", "ResearchIterationCompleted", "ResearchCompleted",
    "ResearchFailed", "ResearchPaused", "ResearchResumed",
    "EvidenceCreated", "ClaimUpdated", "ClaimContradicted",
    "GapDetected", "HighPriorityGapFound",
    "HypothesisCreated", "HypothesisUpdated", "HypothesisChanged",
    "ExperimentRegistered", "ExperimentStarted", "ExperimentCompleted",
    "ExperimentResultAvailable",
    "ReportGenerated", "SourceUpdated", "SourceFetchFailed",
    "JobQueued", "JobStarted", "JobFinished",
    "WatcherTriggered", "ReviewGatePending",
)


@dataclass
class DomainEvent:
    type: str
    project_id: str = ""
    job_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = ""
    ts: str = ""

    def __post_init__(self):
        if not self.event_id:
            self.event_id = "evt_" + uuid.uuid4().hex[:12]
        if not self.ts:
            self.ts = now_iso()

    def to_dict(self) -> dict:
        return {"event_id": self.event_id, "type": self.type,
                "project_id": self.project_id, "job_id": self.job_id,
                "ts": self.ts, "payload": self.payload}


class EventBus:
    """In-process pub/sub. Subscribers get their own bounded queue; a slow
    consumer drops oldest events rather than blocking publishers."""

    def __init__(self, queue_size: int = 512):
        self._subs: dict[str, list[tuple[str, queue.Queue]]] = {}
        self._lock = threading.Lock()
        self._queue_size = queue_size
        self._counter = 0

    def subscribe(self, types: list[str] | None = None) -> tuple[str, "queue.Queue"]:
        """Returns (sub_id, queue). types=None means all events."""
        q: queue.Queue = queue.Queue(maxsize=self._queue_size)
        sub_id = "sub_" + uuid.uuid4().hex[:8]
        with self._lock:
            for t in (types or ["*"]):
                self._subs.setdefault(t, []).append((sub_id, q))
        return sub_id, q

    def unsubscribe(self, sub_id: str) -> None:
        with self._lock:
            for t in list(self._subs):
                self._subs[t] = [s for s in self._subs[t] if s[0] != sub_id]
                if not self._subs[t]:
                    del self._subs[t]

    def publish(self, event: DomainEvent) -> DomainEvent:
        with self._lock:
            targets: list[queue.Queue] = []
            for q_type in ("*", event.type):
                for _sid, q in self._subs.get(q_type, []):
                    targets.append(q)
        for q in targets:
            try:
                q.put_nowait(event)
            except queue.Full:
                try:
                    q.get_nowait()   # drop oldest
                    q.put_nowait(event)
                except (queue.Empty, queue.Full):
                    pass
        return event


class EventPersister:
    """Bridges bus -> append-only platform DB rows (spec #75)."""

    def __init__(self, store, bus: EventBus):
        # store: PlatformDB (avoids circular import; duck-typed persist_event)
        self.store = store
        sub_id, q = bus.subscribe(None)
        self._sub_id = sub_id
        self._q = q
        self._thread = threading.Thread(target=self._loop, name="event-persister",
                                        daemon=True)
        self._stop = threading.Event()
        self._thread.start()
        import atexit
        atexit.register(self.stop)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                ev = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.store.persist_event(ev)
            except Exception:
                pass  # audit is best-effort at dispatch time; bus still works

    def stop(self) -> None:
        """Stop accepting work and DRAIN pending events (one-shot CLIs exit
        immediately after publishing — audit must not be lost)."""
        self._stop.set()
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                ev = self._q.get_nowait()
            except queue.Empty:
                break
            try:
                self.store.persist_event(ev)
            except Exception:
                pass
        self._thread.join(timeout=2.0)


_global_bus: EventBus | None = None
_bus_lock = threading.Lock()


def global_bus() -> EventBus:
    global _global_bus
    with _bus_lock:
        if _global_bus is None:
            _global_bus = EventBus()
        return _global_bus
