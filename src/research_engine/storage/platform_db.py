"""Platform database: jobs, tasks, watchers, events, incidents, model registry.

Lives at <data_dir>/platform.sqlite — GLOBAL across projects (jobs and the
scheduler are platform-level concerns). Uses its own connection handling with
WAL + busy_timeout; all multi-row state changes go through transactions.

Lease claiming is a single atomic conditional UPDATE — two workers can never
hold the same task (spec #8/#119).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research_engine.models.job import JobTask, ResearchJob, TaskStatus, Watcher


class StaleTaskOwner(RuntimeError):
    """Raised when a writer without current ownership attempts a fenced
    mutation (INVARIANT-001/002). Carries expected vs received fence."""

    def __init__(self, task_id: str, worker_id: str, expected_fence: int,
                 received_fence: int | None, reason: str = ""):
        self.task_id = task_id
        self.worker_id = worker_id
        self.expected_fence = expected_fence
        self.received_fence = received_fence
        self.reason = reason
        super().__init__(
            f"STALE_TASK_OWNER task={task_id} worker={worker_id} "
            f"expected_fence={expected_fence} received_fence={received_fence} "
            f"reason={reason}")

_PLATFORM_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 50,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    next_run_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    idempotency_key TEXT,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 50,
    resource_profile TEXT NOT NULL DEFAULT 'CPU_LIGHT',
    data TEXT NOT NULL,
    lease_expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_job ON tasks(job_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

CREATE TABLE IF NOT EXISTS watchers (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    next_run_at TEXT,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS platform_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL,
    project_id TEXT NOT NULL DEFAULT '',
    job_id TEXT NOT NULL DEFAULT '',
    ts TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_pevents_project ON platform_events(project_id, seq);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    job_id TEXT DEFAULT '',
    component TEXT DEFAULT '',
    symptom TEXT DEFAULT '',
    cause TEXT DEFAULT '',
    resolution TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS model_evals (
    id TEXT PRIMARY KEY,
    role TEXT DEFAULT '',
    model TEXT DEFAULT '',
    provider TEXT DEFAULT '',
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PlatformDB:
    def __init__(self, data_dir: str | Path):
        self.path = Path(data_dir) / "platform.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._lock = threading.Lock()
        c = self._conn()
        with c:
            c.executescript(_PLATFORM_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            with self._lock:
                conn = sqlite3.connect(str(self.path), timeout=30.0)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA busy_timeout=10000")
            self._local.conn = conn
        return conn

    # ------------------------------------------------------------ jobs
    # Terminal statuses are ABSORBING: once a job reaches one, stale
    # in-memory objects may not resurrect it into RUNNING/QUEUED etc.
    # (crash/cancel races). Only another terminal write may follow.
    _TERMINAL = ("COMPLETED", "FAILED", "FAILED_PARTIAL", "CANCELLED")

    def save_job(self, job: ResearchJob) -> None:
        job.updated_at = datetime.now(timezone.utc)
        with self._conn() as c:
            c.execute(
                """INSERT INTO jobs(id, project_id, type, status, priority, data,
                                    created_at, updated_at, next_run_at)
                   VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                     priority=excluded.priority, data=excluded.data,
                     updated_at=excluded.updated_at,
                     next_run_at=excluded.next_run_at
                   WHERE jobs.status NOT IN ('COMPLETED','FAILED',
                         'FAILED_PARTIAL','CANCELLED')
                      OR excluded.status IN ('COMPLETED','FAILED',
                         'FAILED_PARTIAL','CANCELLED')""",
                (job.id, job.project_id, job.type, job.status, job.priority,
                 json.dumps(json.loads(job.model_dump_json()), default=str),
                 job.created_at.isoformat(), job.updated_at.isoformat(),
                 job.next_run_at.isoformat() if job.next_run_at else None))

    def get_job(self, job_id: str) -> ResearchJob | None:
        row = self._conn().execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _job_from_row(row)

    def get_task_job(self, job_id: str) -> ResearchJob | None:
        return self.get_job(job_id)

    def list_jobs(self, status: str = "", project_id: str = "",
                  limit: int = 200) -> list[ResearchJob]:
        sql = "SELECT data FROM jobs WHERE 1=1"
        params: list = []
        if status:
            sql += " AND status=?"
            params.append(status)
        if project_id:
            sql += " AND project_id=?"
            params.append(project_id)
        sql += " ORDER BY priority ASC, created_at ASC LIMIT ?"
        params.append(limit)
        return [_job_from_row(r) for r in self._conn().execute(sql, params)]

    def incomplete_jobs(self) -> list[ResearchJob]:
        rows = self._conn().execute(
            "SELECT data FROM jobs WHERE status NOT IN "
            "('COMPLETED','FAILED','FAILED_PARTIAL','CANCELLED')").fetchall()
        return [_job_from_row(r) for r in rows]

    # ------------------------------------------------------------ tasks
    def add_task(self, task: JobTask) -> JobTask:
        task.updated_at = datetime.now(timezone.utc)
        if task.status == TaskStatus.CREATED:
            task.status = TaskStatus.QUEUED
        with self._conn() as c:
            c.execute(
                """INSERT INTO tasks(id, job_id, idempotency_key, status, priority,
                                     resource_profile, data, lease_expires_at,
                                     created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                     data=excluded.data, updated_at=excluded.updated_at,
                     lease_expires_at=excluded.lease_expires_at""",
                (task.id, task.job_id, task.idempotency_key, task.status,
                 task.priority, task.resource_profile,
                 json.dumps(json.loads(task.model_dump_json()), default=str),
                 task.lease_expires_at.isoformat() if task.lease_expires_at else None,
                 task.created_at.isoformat(), task.updated_at.isoformat()))
        return task

    def get_task(self, task_id: str) -> JobTask | None:
        row = self._conn().execute("SELECT data FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _task_from_row(row) if row else None

    def update_task(self, task: JobTask) -> None:
        self.add_task(task)

    def claim_next_task(self, worker_id: str, profiles: dict[str, int],
                        lease_seconds: float, now: datetime | None = None) -> JobTask | None:
        """Atomically claim the highest-priority runnable task under per-profile
        concurrency caps. Expired leases are reclaimable by anyone (#120).

        FENCING: the claim bumps `attempts`, which IS the fencing token
        (INVARIANT-001/002). All subsequent writes by this owner must carry
        that token; the storage layer rejects mismatched ones."""
        now = now or datetime.now(timezone.utc)
        cutoff = (now - timedelta(seconds=lease_seconds)).isoformat()
        now_iso = now.isoformat()
        conn = self._conn()
        with self._lock:
            with conn:
                for profile, cap in sorted(profiles.items()):
                    running = conn.execute(
                        "SELECT COUNT(*) AS n FROM tasks WHERE resource_profile=? "
                        "AND status IN ('CLAIMED','RUNNING') AND lease_expires_at > ?",
                        (profile, now_iso)).fetchone()["n"]
                    if running >= cap:
                        continue
                    row = conn.execute(
                        """SELECT data FROM tasks
                           WHERE resource_profile=?
                             AND ((status IN ('QUEUED','RETRYING'))
                               OR (status IN ('CLAIMED','RUNNING')
                                   AND lease_expires_at IS NOT NULL
                                   AND lease_expires_at <= ?))
                           ORDER BY priority ASC, created_at ASC LIMIT 1""",
                        (profile, now_iso)).fetchone()
                    if row is None:
                        continue
                    task = _task_from_row(row)
                    assert task is not None
                    task.status = TaskStatus.RUNNING
                    task.worker_id = worker_id
                    task.attempts += 1          # fencing token (monotonic)
                    task.updated_at = now
                    task.lease_expires_at = now + timedelta(seconds=lease_seconds)
                    task.heartbeat_at = now
                    conn.execute(
                        """UPDATE tasks SET status=?, data=?, lease_expires_at=?,
                               updated_at=?
                           WHERE id=? AND status IN
                             ('QUEUED','RETRYING','CREATED','CLAIMED','RUNNING')""",
                        (TaskStatus.RUNNING,

                         json.dumps(json.loads(task.model_dump_json()), default=str),
                         task.lease_expires_at.isoformat() if task.lease_expires_at else None,
                         now_iso, task.id))
                    return task
        return None

    def heartbeat(self, task_id: str, worker_id: str,
                  lease_seconds: float, fence: int | None = None) -> bool:
        """Renew a live lease. With `fence` supplied (INVARIANT-002), a stale
        owner's heartbeat is rejected exactly like its writes."""
        now = datetime.now(timezone.utc)
        where = """WHERE id=? AND status IN ('CLAIMED','RUNNING')
                     AND json_extract(data, '$.worker_id')=?"""
        params: list = [task_id, worker_id]
        if fence is not None:
            where += " AND json_extract(data, '$.attempts')=?"
            params.append(fence)
        with self._conn() as c:
            cur = c.execute(
                f"""UPDATE tasks SET data=json_set(data, '$.heartbeat_at', ?),
                        updated_at=?
                   {where}""",
                [now.isoformat(), now.isoformat()] + params)
            renewed = cur.rowcount > 0
            if renewed:
                task = self.get_task(task_id)
                if task is not None:
                    task.lease_expires_at = now + timedelta(seconds=lease_seconds)
                    c.execute("UPDATE tasks SET lease_expires_at=? WHERE id=?",
                              (task.lease_expires_at.isoformat(), task_id))
                    return True
        return False

    def finish_task(self, task_id: str, worker_id: str, ok: bool,
                    result: dict | None = None, error: str = "",
                    error_category: str = "",
                    fence: int | None = None) -> JobTask | None:
        """Terminal write for a claimed task. Ownership-enforced: without a
        matching (worker_id, fence) the write is REJECTED with StaleTaskOwner
        (INVARIANT-001/002) — never silently ignored."""
        current = self.get_task(task_id)
        if current is None:
            return None
        now = datetime.now(timezone.utc)
        if current.status not in (TaskStatus.CLAIMED, TaskStatus.RUNNING):
            raise StaleTaskOwner(
                task_id, worker_id, getattr(current, "attempts", 0),
                fence, reason=f"task already terminal ({current.status})")
        if current.worker_id != worker_id:
            raise StaleTaskOwner(task_id, worker_id,
                                 current.attempts, fence,
                                 reason="task owned by another worker")
        if fence is not None and current.attempts != fence:
            raise StaleTaskOwner(task_id, worker_id,
                                 current.attempts, fence,
                                 reason="fencing token mismatch")
        task = current
        task.updated_at = now
        task.result = result or {}
        task.error = error[:500]
        task.error_category = error_category
        task.lease_expires_at = None
        from research_engine.models.job import TaskStatus as TS
        if ok:
            task.status = TS.SUCCEEDED
        elif task.attempts >= task.max_attempts:
            task.status = TS.DEAD_LETTER   # spec #121
        else:
            task.status = TS.RETRYING
        with self._conn() as c:
            cur = c.execute(
                """UPDATE tasks SET status=?, data=?, lease_expires_at=?, updated_at=?
                   WHERE id=? AND status IN ('CLAIMED','RUNNING')
                     AND json_extract(data,'$.worker_id')=?""",
                (task.status,
                 json.dumps(json.loads(task.model_dump_json()), default=str),
                 task.lease_expires_at.isoformat() if task.lease_expires_at else None,
                 now.isoformat(), task_id, worker_id))
            if cur.rowcount == 0:
                raise StaleTaskOwner(task_id, worker_id, current.attempts, fence,
                                     reason="ownership lost between check and write")
        return task

    def release_task(self, task_id: str, worker_id: str,
                     fence: int | None = None) -> bool:
        """Fenced, ownership-checked release back to QUEUED (pause path)."""
        current = self.get_task(task_id)
        if current is None:
            return False
        if current.worker_id != worker_id or \
                (fence is not None and current.attempts != fence):
            raise StaleTaskOwner(task_id, worker_id, current.attempts, fence,
                                 reason="release by non-owner")
        now = datetime.now(timezone.utc)
        current.status = TaskStatus.QUEUED
        current.lease_expires_at = None
        current.updated_at = now
        with self._conn() as c:
            cur = c.execute(
                """UPDATE tasks SET status=?, data=?, lease_expires_at=?, updated_at=?
                   WHERE id=? AND status IN ('CLAIMED','RUNNING')
                     AND json_extract(data,'$.worker_id')=?""",
                (current.status,
                 json.dumps(json.loads(current.model_dump_json()), default=str),
                 None, now.isoformat(), task_id, worker_id))
            return cur.rowcount > 0

    def requeue_task(self, task_id: str) -> JobTask | None:
        """Manual retry of a dead-lettered/failed task; keeps failure history."""
        task = self.get_task(task_id)
        if task is None:
            return None
        task.status = TaskStatus.QUEUED
        task.attempts = 0
        task.worker_id = ""
        task.lease_expires_at = None
        task.updated_at = datetime.now(timezone.utc)
        with self._conn() as c:
            c.execute(
                "UPDATE tasks SET status=?, data=?, lease_expires_at=?, updated_at=? "
                "WHERE id=?",
                (task.status,
                 json.dumps(json.loads(task.model_dump_json()), default=str),
                 None, task.updated_at.isoformat(), task_id))
        return task

    def tasks_for_job(self, job_id: str) -> list[JobTask]:
        rows = self._conn().execute(
            "SELECT data FROM tasks WHERE job_id=? ORDER BY created_at", (job_id,)).fetchall()
        out = []
        for r in rows:
            try:
                t = _task_from_row(r)
                if t:
                    out.append(t)
            except Exception:
                pass
        return out

    def stale_tasks(self, older_than_s: float) -> list[JobTask]:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_s)).isoformat()
        rows = self._conn().execute(
            "SELECT data FROM tasks WHERE status IN ('CLAIMED','RUNNING') "
            "AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?", (cutoff,)).fetchall()
        out = []
        for r in rows:
            try:
                t = _task_from_row(r)
                if t:
                    out.append(t)
            except Exception:
                pass
        return out

    def has_queued_tasks(self, job_id: str) -> bool:
        n = self._conn().execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE job_id=? AND status IN "
            "('CREATED','QUEUED','RETRYING')", (job_id,)).fetchone()["n"]
        return n > 0

    def task_counts(self) -> dict:
        rows = self._conn().execute(
            "SELECT status, COUNT(*) AS n FROM tasks GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}

    # ------------------------------------------------------------ watchers
    def save_watcher(self, w: Watcher) -> None:
        due = None
        if w.last_run_at is not None:
            due = (w.last_run_at + timedelta(hours=w.frequency_hours)).isoformat()
        elif w.created_at is not None:
            due = (w.created_at + timedelta(seconds=1)).isoformat()
        with self._conn() as c:
            c.execute(
                """INSERT INTO watchers(id, project_id, enabled, next_run_at, data, created_at)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET enabled=excluded.enabled,
                     next_run_at=excluded.next_run_at, data=excluded.data""",
                (w.id, w.project_id, int(w.enabled), due,
                 json.dumps(json.loads(w.model_dump_json()), default=str),
                 w.created_at.isoformat()))

    def get_watcher(self, watcher_id: str) -> Watcher | None:
        row = self._conn().execute(
            "SELECT data FROM watchers WHERE id=?", (watcher_id,)).fetchone()
        if row is None:
            return None
        d = json.loads(row["data"])
        return Watcher.model_validate(d)

    def list_watchers(self, project_id: str = "") -> list[Watcher]:
        sql = ("SELECT data FROM watchers" +
               (" WHERE project_id=?" if project_id else ""))
        rows = self._conn().execute(sql, (project_id,) if project_id else ()).fetchall()
        return [Watcher.model_validate(json.loads(r["data"])) for r in rows]

    def due_watchers(self, now: datetime | None = None) -> list[Watcher]:
        now = now or datetime.now(timezone.utc)
        out = []
        for r in self._conn().execute(
                "SELECT id FROM watchers WHERE enabled=1 AND "
                "(next_run_at IS NULL OR next_run_at <= ?)", now.isoformat()):
            w = self.get_watcher(r["id"])
            if w is not None:
                out.append(w)
        return out

    # ------------------------------------------------------------ events/incidents/model evals
    def persist_event(self, ev) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT OR IGNORE INTO platform_events(event_id, type, project_id,
                       job_id, ts, payload) VALUES(?,?,?,?,?,?)""",
                (ev.event_id, ev.type, ev.project_id, ev.job_id, ev.ts,
                 json.dumps(ev.payload, default=str)))

    def events_for_project(self, project_id: str, limit: int = 100,
                           after_seq: int = 0) -> list[dict]:
        rows = self._conn().execute(
            """SELECT seq, event_id, type, project_id, job_id, ts, payload
               FROM platform_events WHERE project_id=? AND seq>? ORDER BY seq LIMIT ?""",
            (project_id, after_seq, limit)).fetchall()
        return [{"seq": r["seq"], "event_id": r["event_id"], "type": r["type"],
                 "project_id": r["project_id"], "job_id": r["job_id"], "ts": r["ts"],
                 "payload": json.loads(r["payload"])} for r in rows]

    def record_incident(self, job_id: str, component: str, symptom: str,
                        cause: str, resolution: str = "") -> None:
        with self._conn() as c:
            c.execute("INSERT INTO incidents(ts, job_id, component, symptom, cause, "
                      "resolution) VALUES(?,?,?,?,?,?)",
                      (_now_iso(), job_id, component, symptom[:400], cause[:400],
                       resolution[:400]))

    def save_model_eval(self, eval_id: str, data: dict, role: str = "",
                        model: str = "", provider: str = "") -> None:
        with self._conn() as c:
            c.execute("""INSERT INTO model_evals(id, role, model, provider, data, updated_at)
                         VALUES(?,?,?,?,?,?)
                         ON CONFLICT(id) DO UPDATE SET data=excluded.data,
                           updated_at=excluded.updated_at""",
                      (eval_id, role, model, provider, json.dumps(data, default=str),
                       _now_iso()))

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


def _job_from_row(row) -> ResearchJob | None:
    if row is None:
        return None
    try:
        return ResearchJob.model_validate(json.loads(row["data"]))
    except Exception:
        return None


def _task_from_row(row) -> JobTask | None:
    if row is None:
        return None
    try:
        return JobTask.model_validate(json.loads(row["data"]))
    except Exception:
        return None
