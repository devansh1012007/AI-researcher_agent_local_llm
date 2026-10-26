"""SQLite persistence. WAL mode; schema v1; FTS5 for evidence/claim search."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2

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
    opportunity_id TEXT DEFAULT '',
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
CREATE TABLE IF NOT EXISTS startup_markets (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    market_slug TEXT DEFAULT '',
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS market_sizes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    market_id TEXT DEFAULT '',
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS startup_personas (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jtbd (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    segment_id TEXT DEFAULT '',
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alternatives (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS competitor_profiles (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name_lower TEXT DEFAULT '',
    classification TEXT DEFAULT '',
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pricing_plans (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    competitor_name TEXT DEFAULT '',
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS distribution_channels (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tech_shifts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS opportunity_versions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    opportunity_id TEXT DEFAULT '',
    version INTEGER DEFAULT 1,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS opportunity_decisions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    opportunity_id TEXT DEFAULT '',
    decision TEXT DEFAULT '',
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_decisions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    target_kind TEXT,
    target_id TEXT,
    verdict TEXT,
    actor_kind TEXT,
    content_hash TEXT,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    status TEXT,
    iteration INTEGER DEFAULT 0,
    data TEXT NOT NULL
);
"""

# INVARIANT-003: canonical entity identity is enforced by the database.
# Each statement guarded separately so legacy DBs with pre-fix duplicates
# keep working (index skipped + reported) until `repair-startup` runs.
_STARTUP_UNIQUE_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_markets_slug ON startup_markets(project_id, market_slug)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_sizes_evidence ON market_sizes(project_id, json_extract(data,'$.evidence_id'))",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_personas_segment ON startup_personas(project_id, json_extract(data,'$.segment_id'))",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_jtbd_segment ON jtbd(project_id, segment_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_alternatives_name ON alternatives(project_id, LOWER(json_extract(data,'$.name')))",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_competitors_name ON competitor_profiles(project_id, name_lower)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_pricing_plan ON pricing_plans(project_id, competitor_name, json_extract(data,'$.price_raw'), json_extract(data,'$.billing_period'))",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_channels_name ON distribution_channels(project_id, LOWER(json_extract(data,'$.name')))",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_techshift_fp ON tech_shifts(project_id, LOWER(SUBSTR(json_extract(data,'$.description'),1,80)))",
]


def parse_payload_timestamp(value) -> datetime | None:
    """Parse a persisted payload ``created_at`` into an aware UTC datetime.

    This is the CANONICAL parser for the ``created_at`` convention of the
    stored JSON payloads (the ``data`` blob written by this module): an
    ISO-8601 UTC string such as ``"2026-10-22T09:05:24.411110Z"``. Returns
    ``None`` when the value is absent or unusable - the caller then treats
    the row's age as UNKNOWN.

    Decision: the parser lives with the payload format, not with one of its
    readers.
    Why: the convention belongs to the ``data`` blob this module writes, so
    every reader (the graph store, the duplicate repair) must share ONE
    implementation. A parser imported from a consumer module makes the
    storage layer depend on its callers - and two parsers would drift.

    Why parsing and not string comparison: pydantic omits the fractional
    part when the microseconds are exactly 0, so the TEXT
    ``'2026-01-01T00:00:00Z'`` is GREATER than
    ``'2026-01-01T00:00:00.500000Z'`` ('Z' > '.') although it is the older
    instant. Only a parsed datetime orders chronologically.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        # A malformed stamp is NOT a valid age. It is reported as unknown
        # (the caller sorts it last and counts it) instead of being guessed.
        return None
    if parsed.tzinfo is None:
        # a naive stamp is read as UTC: every persisted stamp is UTC
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
        self._ensure_startup_indexes()

    def _ensure_startup_indexes(self) -> None:
        """INVARIANT-003 backstop: unique natural-key indexes. On legacy DBs
        still carrying duplicates, index creation fails — recorded (not fatal)
        so `research repair-startup` can dedupe and complete the upgrade."""
        self.skipped_unique_indexes: list[str] = []
        c = self._conn()
        for stmt in _STARTUP_UNIQUE_INDEXES:
            try:
                with c:
                    c.execute(stmt)
            except sqlite3.IntegrityError:
                self.skipped_unique_indexes.append(stmt)

    def _migrate(self) -> None:
        """Lightweight additive migrations for DBs created by older engine versions."""
        c = self._conn()
        for table, col, decl in (
            ("claims", "iteration", "INTEGER DEFAULT 0"),
            ("experiments", "opportunity_id", "TEXT DEFAULT ''"),
        ):
            cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
            if col not in cols:
                with c:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        with c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS questions ("
                "id TEXT PRIMARY KEY, project_id TEXT NOT NULL, "
                "status TEXT, iteration INTEGER DEFAULT 0, data TEXT NOT NULL)"
            )
            c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
        self._backfill_experiment_opportunity_ids(c)

    def _backfill_experiment_opportunity_ids(self, c) -> None:
        """P3-9: backfill experiments.opportunity_id ONLY when unambiguous."""
        import json as _json
        import re as _re
        rows = c.execute(
            "SELECT id, project_id, hypothesis_id, data FROM experiments "
            "WHERE opportunity_id IS NULL OR opportunity_id = ''"
        ).fetchall()
        for r in rows:
            try:
                d = _json.loads(r["data"])
            except Exception:
                continue
            opp_id = str(d.get("opportunity_id") or "").strip()
            if not opp_id:
                note = str(d.get("decision_note") or "")
                m = _re.search(r"(?:^|;\s*)opp=(opp_[A-Za-z0-9_\-]+)", note)
                if m:
                    opp_id = m.group(1)
            if not opp_id and r["hypothesis_id"]:
                asm_rows = c.execute(
                    "SELECT DISTINCT opportunity_id FROM assumptions2 "
                    "WHERE project_id=? AND json_extract(data, '$.hypothesis_id')=? "
                    "AND opportunity_id IS NOT NULL AND opportunity_id != ''",
                    (r["project_id"], r["hypothesis_id"]),
                ).fetchall()
                distinct_opps = [ar["opportunity_id"] for ar in asm_rows if ar["opportunity_id"]]
                if len(distinct_opps) == 1:
                    opp_id = distinct_opps[0]
            if opp_id:
                d["opportunity_id"] = opp_id
                with c:
                    c.execute(
                        "UPDATE experiments SET opportunity_id=?, data=? WHERE id=?",
                        (opp_id, _json.dumps(d, default=str), r["id"]),
                    )

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
        # BUG-07 fix: one FTS row per entity — replace, never duplicate
        with self._conn() as c:
            c.execute("DELETE FROM evidence_fts WHERE entity_id=?", (entity_id,))
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
