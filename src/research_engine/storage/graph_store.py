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
from datetime import datetime, timezone

from research_engine.storage.database import Database, parse_payload_timestamp


# C22 audit - id text is NOT a creation order any more. The entity id
# generator mints ULIDs, rows written before that change keep their old
# `<prefix>_%06d` ids (which sort AFTER a ULID once the counter passes
# 100000), the prefix differs per entity type (`ent_*` vs `pap_*`, so a
# mixed population groups by prefix and never by time) and a relationship id
# is a CONTENT hash of (source, target, type). The consumers were audited:
#   * `entities()` -> `cli/main.py` display (determinism is enough) and
#     `specialists/startup/cli_glue.py:18`, which uses only `len()` and is
#     therefore order-independent.
#   * `specialists/startup/competitors.py::build_profiles` merges the
#     `company` and the `competitor` lists. Within ONE type there is no age
#     contest at all: `upsert_entity` resolves a single row per
#     (project, type, name_key). ACROSS the two types the winner is the
#     LIST CONCATENATION - the `competitor` row is processed last and
#     overwrites the profile fields - not the age.
#   * `relationships()` -> `find_relationship` (unique match), `evidence_density`
#     (no callers) and `neighbors` (one test) need determinism only.
# Hence: `entities()` orders by the payload `created_at` (the only creation
# order the rows carry), `relationships()` keeps a deterministic content-hash
# order, and neither claims oldest-first semantics it cannot honour.


def _utc_now_iso() -> str:
    """UTC ISO-8601 stamp in the same shape pydantic writes for
    ``Entity.created_at`` (trailing ``Z``, fractional part omitted when 0)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _entity_order_key(entity: GraphEntity) -> tuple:
    """Creation-order key for `GraphStore.entities()`.

    Known timestamps first (oldest first), rows with an unknown age last,
    ``id`` breaks every tie so the order is total and deterministic.
    """
    stamp = parse_payload_timestamp(entity.created_at)
    if stamp is None:
        return (1, entity.id)
    return (0, stamp, entity.id)


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
            "SELECT id, data FROM graph_entities "
            "WHERE project_id=? AND type=? AND name_key=?",
            (e.project_id, e.type, e.name_key)).fetchone()
        existing_data = None
        if row is not None:
            e.id = row["id"]
            existing_data = row["data"]
        else:
            # the caller may address an existing entity by id
            prior = self._conn().execute(
                "SELECT data FROM graph_entities WHERE id=?", (e.id,)).fetchone()
            existing_data = prior["data"] if prior is not None else None
        # Decision: the age of an existing row is decided ONCE, when the row
        #   is first written, and is never rewritten afterwards - not even
        #   when that age is UNKNOWN.
        # Why: a row written before the payload carried a timestamp has an
        #   empty stamp. Back-filling it with the time of the next upsert
        #   would silently turn an UNKNOWN age into "newest", which is the
        #   opposite of the truth: that row is older than every row written
        #   after the change. The consumers that pick a REPRESENTATIVE row
        #   (competitor profiles, pain clustering) would then keep the wrong
        #   one, and `entities()` would stop sorting oldest-first.
        # Constraint: the stored stamp wins over the incoming one, so the
        #   creation time of an existing entity is immutable. A NEW row is
        #   stamped now - there is no older age to preserve.
        if existing_data is not None:
            e.created_at = json.loads(existing_data).get("created_at") or ""
        elif not e.created_at:
            e.created_at = _utc_now_iso()
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
        """Entities of a project, OLDEST FIRST by the payload ``created_at``.

        Decision: creation order comes from the row payload's
        ``created_at``, never from the id text.
        Why: the id text is not a creation order (see the C22 audit above):
        legacy rows keep their old counter ids and the prefix differs per
        type. The payload stamp is the only creation order the rows carry,
        so it is the order a reader gets.
        Constraint: rows written before the payload carried a timestamp
        have an empty ``created_at``. Their age is UNKNOWN, so they sort
        last and are tie-broken by id; the order is total and deterministic.
        An UNKNOWN age is never back-filled by a later upsert (see
        `upsert_entity`), so the promise holds for legacy rows too.
        """
        sql = "SELECT data FROM graph_entities WHERE project_id=?"
        params: tuple = (project_id,)
        if type_:
            sql += " AND type=?"
            params += (type_,)
        ents = [GraphEntity(**json.loads(r["data"]))
                for r in self._conn().execute(sql, params).fetchall()]
        ents.sort(key=_entity_order_key)
        return ents

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
        """Relationships of a project in a deterministic, stable order.

        Decision: the order is the relationship id, which is a CONTENT hash
        of (source, target, type) - NOT a creation order.
        Why: a relationship row carries no timestamp, so creation order is
        not representable; claiming one would be a fiction. Every consumer
        needs determinism only (`find_relationship` matches a unique pair,
        `evidence_density` counts, `neighbors` lists).
        Constraint: do not read this order as "oldest first", and do not
        add a timestamp field to `Relationship` to make it look like one.
        """
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
