"""Caches: HTTP responses, search results, LLM results.

Cache key = hash(provider + operation + params). SQLite-backed, per-project DB
plus a global cache DB shared across projects so identical fetches are never paid twice.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import quote_plus  # noqa: F401  (kept for future key shaping)

log = logging.getLogger(__name__)


def cache_key(*parts: object) -> str:
    joined = json.dumps([str(p) for p in parts], sort_keys=True)
    return hashlib.sha256(joined.encode()).hexdigest()


class KVCache:
    """Tiny persistent KV cache with TTL."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_lock = threading.Lock()  # serializes first-connection pragmas

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            with self._init_lock:
                conn = sqlite3.connect(str(self.path), timeout=30.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, expires REAL)"
                )
            self._local.conn = conn
        return conn

    def get(self, key: str):
        row = self._conn().execute(
            "SELECT v, expires FROM cache WHERE k=?", (key,)
        ).fetchone()
        if not row:
            return None
        if row[1] and row[1] < time.time():
            return None
        try:
            return json.loads(row[0])
        except Exception:
            log.warning("corrupted cache entry removed: %s", key[:12])
            self.delete(key)
            return None

    def put(self, key: str, value, ttl_hours: float = 168) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO cache(k, v, expires) VALUES(?,?,?)",
                (key, json.dumps(value, default=str), time.time() + ttl_hours * 3600),
            )

    def delete(self, key: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM cache WHERE k=?", (key,))
