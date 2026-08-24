"""SQLite persistence. WAL mode; schema v1; FTS5 for evidence/claim search."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS problems (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS branches (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    type TEXT,
    status TEXT,
    iteration INTEGER,
    priority REAL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project_id, status);

CREATE TABLE IF NOT EXISTS queries (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    executed INTEGER DEFAULT 0,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS search_results (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    query_id TEXT,
    url TEXT,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    canonical_url TEXT,
    content_hash TEXT,
    domain TEXT,
    source_tier INTEGER,
    status TEXT,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sources_url ON sources(project_id, canonical_url);
CREATE INDEX IF NOT EXISTS idx_sources_hash ON sources(project_id, content_hash);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    source_id TEXT,
    content_hash TEXT,
    status TEXT,
    data TEXT NOT NULL  -- text kept in separate fts table; full text here may be large but bounded by config
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    sequence INTEGER,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id);

CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    dedup_key TEXT,
    branch TEXT,
    kind TEXT,
    iteration INTEGER DEFAULT 0,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_dedup ON claims(project_id, dedup_key);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    claim_text_lower TEXT,
    source_id TEXT,
    document_id TEXT,
    status TEXT,
    tier INTEGER,
    iteration INTEGER,
    quote_hash TEXT,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence(project_id, source_id);
CREATE INDEX IF NOT EXISTS idx_evidence_quote ON evidence(project_id, quote_hash);

CREATE TABLE IF NOT EXISTS gaps (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    resolved INTEGER DEFAULT 0,
    importance REAL,
    category TEXT,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contradictions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    resolved INTEGER DEFAULT 0,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS iterations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    number INTEGER,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metrics (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    iteration INTEGER,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind TEXT,
    path TEXT,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS opportunities (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    data TEXT NOT NULL
);

-- FTS5 full-text search over claims and evidence quotes
CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
    entity_id UNINDEXED, project_id UNINDEXED, kind UNINDEXED, text
);
"""


_EXTRA_TABLES = """
CREATE TABLE IF NOT EXISTS falsification_tests (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_versions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    observed_at TEXT,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hypotheses (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    status TEXT,
    domain TEXT,
    version INTEGER DEFAULT 1,
    alternative_of TEXT DEFAULT '',
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hypothesis_versions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    hypothesis_id TEXT NOT NULL,
    version INTEGER,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assumptions2 (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind TEXT,
    status TEXT,
    opportunity_id TEXT DEFAULT '',
    data TEXT NOT NULL
);
-- note: hypothesis_id lives inside the JSON payload; filter via list+filter
-- or add an indexed column in _migrate if query volume demands it.
CREATE TABLE IF NOT EXISTS research_questions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    gap_ref TEXT,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS methodologies (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    hypothesis_id TEXT NOT NULL,
    tier TEXT,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    hypothesis_id TEXT NOT NULL,
    status TEXT,
    risk_level TEXT,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiment_results (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    experiment_id TEXT NOT NULL,
    data TEXT NOT NULL
);
"""


class Database:
    """Thread-safe SQLite wrapper. One connection per thread via threading.local."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_lock = threading.Lock()  # serializes first-connection pragmas/DDL
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            with self._init_lock:
                conn = sqlite3.connect(str(self.db_path), timeout=30.0)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def _init_schema(self) -> None:
        c = self._conn()
        with c:
            c.executescript(_SCHEMA)
            c.executescript(_EXTRA_TABLES)
            row = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None:
                c.execute("INSERT INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
            elif int(row["value"]) > SCHEMA_VERSION:
                raise RuntimeError(f"DB schema v{row['value']} newer than engine schema v{SCHEMA_VERSION}")
        self._migrate()

    def _migrate(self) -> None:
        """Lightweight additive migrations for DBs created by older engine versions."""
        c = self._conn()
        for table, col, decl in (("claims", "iteration", "INTEGER DEFAULT 0"),):
            cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
            if col not in cols:
                with c:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

    # -- generic CRUD ------------------------------------------------------
    def upsert(self, table: str, entity_id: str, project_id: str, data: dict,
               cols: dict[str, object] | None = None) -> None:
        cols = cols or {}
        payload = json.dumps(data, default=str)
        insert_cols = ["id", "project_id", "data"]
        insert_vals = [entity_id, project_id, payload]
        if cols:
            insert_cols += list(cols.keys())
            insert_vals += list(cols.values())
        placeholders = ", ".join(["?"] * len(insert_vals))
        set_clause = "data=?" + ((", " + ", ".join(f"{k}=?" for k in cols)) if cols else "")
        update_vals = [payload] + list(cols.values())
        sql = (
            f"INSERT INTO {table}({', '.join(insert_cols)}) VALUES({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {set_clause}"
        )
        with self._conn() as c:
            c.execute(sql, (*insert_vals, *update_vals))

    def get(self, table: str, entity_id: str) -> dict | None:
        row = self._conn().execute(
            f"SELECT data FROM {table} WHERE id=?", (entity_id,)
        ).fetchone()
        return json.loads(row["data"]) if row else None

    def list(self, table: str, project_id: str, where: str = "", params: tuple = ()) -> list[dict]:
        sql = f"SELECT data FROM {table} WHERE project_id=?"
        if where:
            sql += f" AND {where}"
        rows = self._conn().execute(sql, (project_id, *params)).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def delete(self, table: str, entity_id: str) -> None:
        with self._conn() as c:
            c.execute(f"DELETE FROM {table} WHERE id=?", (entity_id,))

    def count(self, table: str, project_id: str, where: str = "", params: tuple = ()) -> int:
        sql = f"SELECT COUNT(*) AS n FROM {table} WHERE project_id=?"
        if where:
            sql += f" AND {where}"
        return self._conn().execute(sql, (project_id, *params)).fetchone()["n"]

    def execute(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self._conn().execute(sql, params).fetchall()

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # -- FTS ---------------------------------------------------------------
    def fts_index(self, entity_id: str, project_id: str, kind: str, text: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO evidence_fts(entity_id, project_id, kind, text) VALUES(?,?,?,?)",
                (entity_id, project_id, kind, text),
            )

    def fts_search(self, project_id: str, query: str, kind: str = "", limit: int = 20) -> list[str]:
        sql = ("SELECT entity_id FROM evidence_fts WHERE project_id=? AND evidence_fts MATCH ? "
               + ("AND kind=? " if kind else "") + "ORDER BY rank LIMIT ?")
        params = (project_id, query, *((kind,) if kind else ()), limit)
        try:
            rows = self.execute(sql, params)
        except Exception:
            # fall back to LIKE for non-FTS-safe query strings
            like = f"%{query}%"
            sql = "SELECT entity_id FROM evidence_fts WHERE project_id=? AND text LIKE ? LIMIT ?"
            rows = self.execute(sql, (project_id, like, limit))
        return [r["entity_id"] for r in rows]
