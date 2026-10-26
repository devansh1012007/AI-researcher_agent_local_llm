"""Vector store over SQLite: entity_id -> embedding blob.

Deliberately simple (spec #46): brute-force cosine over a single table is fine
for tens of thousands of chunks on a laptop. The interface is abstract enough
to swap for sqlite-vec/FAISS later without touching retrieval code.
"""
from __future__ import annotations

import json
import struct
import threading

from research_engine.providers.embeddings.base import cosine
from research_engine.storage.database import Database


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


class VectorStore:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS vectors (
        entity_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        dim INTEGER,
        vec BLOB,
        model TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_vec_proj ON vectors(project_id, kind);
    """

    def __init__(self, db: Database, model_name: str = "hashing"):
        self.db = db
        self.model_name = model_name
        self._lock = threading.Lock()
        with self.db._conn() as c:
            c.executescript(self.SCHEMA)

    def upsert(self, project_id: str, entity_id: str, kind: str, vec: list[float]) -> None:
        with self._lock:
            with self.db._conn() as c:
                c.execute(
                    "INSERT INTO vectors(entity_id, project_id, kind, dim, vec, model) "
                    "VALUES(?,?,?,?,?,?) ON CONFLICT(entity_id) DO UPDATE SET "
                    "vec=excluded.vec, dim=excluded.dim, model=excluded.model",
                    (entity_id, project_id, kind, len(vec), _pack(vec), self.model_name))

    def get(self, entity_id: str) -> list[float] | None:
        row = self.db._conn().execute(
            "SELECT vec FROM vectors WHERE entity_id=?", (entity_id,)).fetchone()
        return _unpack(row[0]) if row else None

    def search(self, project_id: str, query_vec: list[float], kind: str = "",
               limit: int = 20) -> list[tuple[str, float]]:
        """Brute-force cosine; returns [(entity_id, similarity)] best-first."""
        sql = "SELECT entity_id, vec FROM vectors WHERE project_id=?"
        params: list = [project_id]
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        rows = self.db._conn().execute(sql, tuple(params)).fetchall()
        scored = []
        qnorm_ok = any(abs(x) > 1e-9 for x in query_vec)
        for entity_id, blob in rows:
            if not qnorm_ok:
                continue
            scored.append((entity_id, cosine(query_vec, _unpack(blob))))
        scored.sort(key=lambda t: -t[1])
        return scored[:limit]

    def count(self, project_id: str) -> int:
        row = self.db._conn().execute(
            "SELECT COUNT(*) FROM vectors WHERE project_id=?", (project_id,)).fetchone()
        return row[0]
