"""Research graph: generic entity + relationship storage in SQLite.

Phase 2 knowledge model. Entities are typed nodes (paper, method, dataset,
competitor, pain_point, market_signal, opportunity, concept...) with JSON
attributes; relationships are typed edges with confidence and evidence provenance.

Deliberately relational (no Neo4j) per spec - the workload is small and local.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field

from research_engine.storage.database import Database


@dataclass
class GraphEntity:
    id: str = ""
    project_id: str = ""
    type: str = ""                    # paper|method|dataset|benchmark|concept|company|
                                      # competitor|pain_point|segment|market_signal|
                                      # opportunity|price_observation|hypothesis
    name: str = ""
    name_key: str = ""                # normalized for entity resolution
    attributes: dict = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class Relationship:
    id: str = ""
    project_id: str = ""
    source_id: str = ""               # entity id
    target_id: str = ""               # entity id
    relationship_type: str = ""       # supports|contradicts|extends|compares|uses|
                                      # benchmarks|evaluated_on|competes_with|signals|
                                      # priced_at|part_of|addresses|follows_up
    confidence: float = 0.5
    evidence_ids: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def normalize_name(name: str) -> str:
    """Conservative entity normalization: lowercase alnum tokens, sorted.

    Over-merging is worse than under-merging; ambiguity is preserved upstream.
    """
    tokens = re.findall(r"[a-z0-9]+", (name or "").lower())
    stopwords = {"inc", "llc", "ltd", "gmbh", "corp", "corporation", "the", "co"}
    return " ".join(sorted(t for t in tokens if t not in stopwords))


class GraphStore:
    """Entity/relationship persistence + graph queries."""

    def __init__(self, db: Database):
        self.db = db
        self._lock = threading.Lock()
        self._ensure_schema()

    def _conn(self):
        return self.db._conn()

    def _ensure_schema(self) -> None:
        with self._init_lock_wrap():
            self._conn().executescript("""
            CREATE TABLE IF NOT EXISTS graph_entities (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                type TEXT NOT NULL,
                name_key TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ge_type ON graph_entities(project_id, type);
            CREATE INDEX IF NOT EXISTS idx_ge_name ON graph_entities(project_id, type, name_key);

            CREATE TABLE IF NOT EXISTS graph_relationships (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                rel_type TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_gr_src ON graph_relationships(project_id, source_id);
            CREATE INDEX IF NOT EXISTS idx_gr_tgt ON graph_relationships(project_id, target_id);
            CREATE INDEX IF NOT EXISTS idx_gr_type ON graph_relationships(project_id, rel_type);
            """)

    def _init_lock_wrap(self):
        lock = getattr(self.db, "_graph_ddl_lock", None)
        if lock is None:
            import threading as _t
            lock = _t.Lock()
            setattr(self.db, "_graph_ddl_lock", lock)
        return lock

    # -- entities ----------------------------------------------------------
    def upsert_entity(self, e: GraphEntity) -> GraphEntity:
        if not e.id:
            from research_engine.core.ids import next_id
            prefix = {"paper": "pap"}.get(e.type, "ent")
            e.id = next_id(prefix)
        if not e.name_key:
            e.name_key = normalize_name(e.name)
        # entity resolution: same project+type+name_key -> same node
        row = self._conn().execute(
            "SELECT id FROM graph_entities WHERE project_id=? AND type=? AND name_key=?",
            (e.project_id, e.type, e.name_key)).fetchone()
        if row is not None:
            e.id = row["id"]
        payload = json.dumps(e.to_dict(), default=str)
        with self._lock:
            with self._conn() as c:
                c.execute(
                    "INSERT INTO graph_entities(id, project_id, type, name_key, data) "
                    "VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                    (e.id, e.project_id, e.type, e.name_key, payload))
        return e

    def get_entity(self, entity_id: str) -> GraphEntity | None:
        row = self._conn().execute(
            "SELECT data FROM graph_entities WHERE id=?", (entity_id,)).fetchone()
        return GraphEntity(**json.loads(row["data"])) if row else None

    def find_entity(self, project_id: str, type_: str, name: str) -> GraphEntity | None:
        row = self._conn().execute(
            "SELECT data FROM graph_entities WHERE project_id=? AND type=? AND name_key=?",
            (project_id, type_, normalize_name(name))).fetchone()
        return GraphEntity(**json.loads(row["data"])) if row else None

    def entities(self, project_id: str, type_: str | None = None) -> list[GraphEntity]:
        sql = "SELECT data FROM graph_entities WHERE project_id=?"
        params: tuple = (project_id,)
        if type_:
            sql += " AND type=?"
            params += (type_,)
        return [GraphEntity(**json.loads(r["data"]))
                for r in self._conn().execute(sql + " ORDER BY id", params).fetchall()]

    # -- relationships -------------------------------------------------------
    def add_relationship(self, r: Relationship) -> Relationship:
        if not r.id:
            from research_engine.core.ids import stable_hash
            # deterministic id: same pair+type collapses to one edge
            key = "|".join(sorted([r.source_id, r.target_id])) + "|" + r.relationship_type
            r.id = "rel_" + stable_hash(key)[:16]
        payload = json.dumps(r.to_dict(), default=str)
        with self._lock:
            with self._conn() as c:
                c.execute(
                    "INSERT INTO graph_relationships(id, project_id, source_id, target_id,"
                    " rel_type, data) VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                    (r.id, r.project_id, r.source_id, r.target_id, r.relationship_type, payload))
        return r

    def relationships(self, project_id: str, rel_type: str | None = None,
                      entity_id: str | None = None) -> list[Relationship]:
        sql = "SELECT data FROM graph_relationships WHERE project_id=?"
        params: list = [project_id]
        if rel_type:
            sql += " AND rel_type=?"
            params.append(rel_type)
        if entity_id:
            sql += " AND (source_id=? OR target_id=?)"
            params.extend([entity_id, entity_id])
        return [Relationship(**json.loads(r["data"]))
                for r in self._conn().execute(sql + " ORDER BY id", tuple(params)).fetchall()]

    def find_relationship(self, project_id: str, a: str, b: str, rel_type: str) -> Relationship | None:
        for r in self.relationships(project_id, rel_type):
            if {r.source_id, r.target_id} == {a, b}:
                return r
        return None

    # -- graph analytics -----------------------------------------------------
    def evidence_density(self, project_id: str, type_: str) -> dict[str, int]:
        """Evidence count attached to each entity of a type (via relationships)."""
        counts: dict[str, int] = {}
        for ent in self.entities(project_id, type_):
            ev = set()
            for rel in self.relationships(project_id, entity_id=ent.id):
                ev.update(rel.evidence_ids)
            counts[ent.id] = len(ev)
        return counts

    def neighbors(self, project_id: str, entity_id: str) -> list[tuple[Relationship, GraphEntity]]:
        out = []
        for rel in self.relationships(project_id, entity_id=entity_id):
            other = rel.target_id if rel.source_id == entity_id else rel.source_id
            ent = self.get_entity(other)
            if ent:
                out.append((rel, ent))
        return out
