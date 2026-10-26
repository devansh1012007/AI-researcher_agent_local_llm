"""Cross-project relational knowledge base (Phase 8).

Generalizes `MarketKnowledgeBase` into a domain-agnostic relational store at
`<data_dir>/_global/relational_kb.sqlite` with three tables:
- `kb_entities`: canonical entities keyed by `(namespace, entity_type, natural_key)`
- `kb_observations`: quote-grounded observations linked to `(entity_id, project_id, evidence_id)`
- `kb_relations`: typed edges between entities within a namespace

Enforces INV-003 (idempotent natural-key upserts) and INV-013 (project isolation:
`seed_project` is a no-op unless `use_global_kb=True` is explicitly passed).
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from research_engine.core.ids import next_id, stable_hash

_RELATIONAL_KB_SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_entities (
    id TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    natural_key TEXT NOT NULL,
    name TEXT NOT NULL,
    attributes TEXT NOT NULL,
    first_project_id TEXT NOT NULL,
    last_project_id TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_observed_at TEXT NOT NULL,
    UNIQUE(namespace, entity_type, natural_key)
);
CREATE INDEX IF NOT EXISTS idx_kb_entities_ns_type ON kb_entities(namespace, entity_type);

CREATE TABLE IF NOT EXISTS kb_observations (
    id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_tier INTEGER NOT NULL,
    claim_text TEXT NOT NULL,
    quote TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    data TEXT NOT NULL,
    UNIQUE(entity_id, project_id, evidence_id)
);
CREATE INDEX IF NOT EXISTS idx_kb_obs_entity ON kb_observations(entity_id);

CREATE TABLE IF NOT EXISTS kb_relations (
    id TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    from_entity_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    to_entity_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    evidence_id TEXT DEFAULT '',
    observed_at TEXT NOT NULL,
    data TEXT NOT NULL,
    UNIQUE(namespace, from_entity_id, relation_type, to_entity_id)
);
CREATE INDEX IF NOT EXISTS idx_kb_rel_ns ON kb_relations(namespace);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_natural_key(raw: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (raw or "").strip().lower()).strip("-")
    return cleaned or "unnamed"


class RelationalKnowledgeBase:
    """Domain-agnostic cross-project relational entity & observation store."""

    def __init__(self, data_dir: str | Path):
        self.root = Path(data_dir) / "_global"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "relational_kb.sqlite"
        self._local = threading.local()
        self._lock = threading.Lock()
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            with self._lock:
                conn = sqlite3.connect(str(self.db_path), timeout=30.0)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    def _init_schema(self) -> None:
        c = self._conn()
        with self._lock, c:
            c.executescript(_RELATIONAL_KB_SCHEMA)

    def upsert_entity(
        self,
        namespace: str,
        entity_type: str,
        natural_key: str,
        name: str,
        attributes: dict[str, Any] | None = None,
        project_id: str = "",
        observed_at: str = "",
    ) -> dict[str, Any]:
        """Idempotently upsert an entity by (namespace, entity_type, natural_key) (INV-003)."""
        ns = (namespace or "generic:default").strip().lower()
        etype = (entity_type or "entity").strip().lower()
        nkey = normalize_natural_key(natural_key or name)
        now = observed_at or _now_iso()
        attrs = dict(attributes or {})
        ent_id = f"kb_ent_{stable_hash(f'{ns}:{etype}:{nkey}')[:16]}"

        c = self._conn()
        with self._lock, c:
            existing = c.execute(
                "SELECT * FROM kb_entities WHERE namespace=? AND entity_type=? AND natural_key=?",
                (ns, etype, nkey),
            ).fetchone()
            if existing is None:
                c.execute(
                    """INSERT INTO kb_entities(
                           id, namespace, entity_type, natural_key, name, attributes,
                           first_project_id, last_project_id, first_seen_at, last_observed_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        ent_id,
                        ns,
                        etype,
                        nkey,
                        name or nkey,
                        json.dumps(attrs, default=str),
                        project_id,
                        project_id,
                        now,
                        now,
                    ),
                )
            else:
                ent_id = existing["id"]
                merged_attrs = json.loads(existing["attributes"] or "{}")
                merged_attrs.update(attrs)
                last_obs = max(str(existing["last_observed_at"] or ""), str(now))
                c.execute(
                    """UPDATE kb_entities
                       SET name=?, attributes=?, last_project_id=?, last_observed_at=?
                       WHERE id=?""",
                    (
                        name or existing["name"],
                        json.dumps(merged_attrs, default=str),
                        project_id or existing["last_project_id"],
                        last_obs,
                        ent_id,
                    ),
                )
            row = c.execute("SELECT * FROM kb_entities WHERE id=?", (ent_id,)).fetchone()
        return self._row_to_entity(row)

    def record_observation(
        self,
        entity_id: str,
        project_id: str,
        evidence_id: str,
        claim_text: str,
        quote: str = "",
        source_url: str = "",
        source_tier: int = 5,
        observed_at: str = "",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Idempotently record a quote-grounded observation for an entity."""
        now = observed_at or _now_iso()
        obs_id = f"kb_obs_{stable_hash(f'{entity_id}:{project_id}:{evidence_id}')[:16]}"
        payload = json.dumps(data or {}, default=str)
        c = self._conn()
        with self._lock, c:
            c.execute(
                """INSERT INTO kb_observations(
                       id, entity_id, project_id, evidence_id, source_url,
                       source_tier, claim_text, quote, observed_at, data
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(entity_id, project_id, evidence_id) DO UPDATE SET
                       claim_text=excluded.claim_text,
                       quote=excluded.quote,
                       source_url=excluded.source_url,
                       source_tier=excluded.source_tier,
                       observed_at=excluded.observed_at,
                       data=excluded.data""",
                (
                    obs_id,
                    entity_id,
                    project_id,
                    evidence_id,
                    source_url,
                    int(source_tier),
                    claim_text,
                    quote,
                    now,
                    payload,
                ),
            )
            row = c.execute(
                "SELECT * FROM kb_observations WHERE entity_id=? AND project_id=? AND evidence_id=?",
                (entity_id, project_id, evidence_id),
            ).fetchone()
        return dict(row) if row else {}

    def link_entities(
        self,
        namespace: str,
        from_entity_id: str,
        relation_type: str,
        to_entity_id: str,
        project_id: str = "",
        evidence_id: str = "",
        observed_at: str = "",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Idempotently create or update a directed relation between two entities."""
        ns = (namespace or "generic:default").strip().lower()
        rel = (relation_type or "related_to").strip().lower()
        now = observed_at or _now_iso()
        rel_id = f"kb_rel_{stable_hash(f'{ns}:{from_entity_id}:{rel}:{to_entity_id}')[:16]}"
        payload = json.dumps(data or {}, default=str)
        c = self._conn()
        with self._lock, c:
            c.execute(
                """INSERT INTO kb_relations(
                       id, namespace, from_entity_id, relation_type, to_entity_id,
                       project_id, evidence_id, observed_at, data
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(namespace, from_entity_id, relation_type, to_entity_id) DO UPDATE SET
                       project_id=excluded.project_id,
                       evidence_id=excluded.evidence_id,
                       observed_at=excluded.observed_at,
                       data=excluded.data""",
                (rel_id, ns, from_entity_id, rel, to_entity_id, project_id, evidence_id, now, payload),
            )
            row = c.execute(
                """SELECT * FROM kb_relations
                   WHERE namespace=? AND from_entity_id=? AND relation_type=? AND to_entity_id=?""",
                (ns, from_entity_id, rel, to_entity_id),
            ).fetchone()
        return dict(row) if row else {}

    def lookup_namespace(self, namespace: str, entity_type: str = "") -> dict[str, Any]:
        ns = (namespace or "generic:default").strip().lower()
        c = self._conn()
        if entity_type:
            ent_rows = c.execute(
                "SELECT * FROM kb_entities WHERE namespace=? AND entity_type=? ORDER BY name ASC",
                (ns, entity_type.strip().lower()),
            ).fetchall()
        else:
            ent_rows = c.execute(
                "SELECT * FROM kb_entities WHERE namespace=? ORDER BY entity_type ASC, name ASC",
                (ns,),
            ).fetchall()
        entities = [self._row_to_entity(r) for r in ent_rows]
        ent_ids = [e["id"] for e in entities]
        observations: list[dict[str, Any]] = []
        if ent_ids:
            placeholders = ",".join("?" * len(ent_ids))
            obs_rows = c.execute(
                f"SELECT * FROM kb_observations WHERE entity_id IN ({placeholders}) ORDER BY observed_at DESC",
                tuple(ent_ids),
            ).fetchall()
            observations = [
                {**dict(r), "data": json.loads(r["data"] or "{}")}
                for r in obs_rows
            ]
        rel_rows = c.execute(
            "SELECT * FROM kb_relations WHERE namespace=? ORDER BY observed_at DESC",
            (ns,),
        ).fetchall()
        relations = [
            {**dict(r), "data": json.loads(r["data"] or "{}")}
            for r in rel_rows
        ]
        return {
            "namespace": ns,
            "entities": entities,
            "observations": observations,
            "relations": relations,
        }

    def freshness_summary(self, namespace: str, today: str = "") -> dict[str, Any]:
        """Compute freshness status ('fresh' | 'aging' | 'stale') for entities in a namespace."""
        today_d = date.fromisoformat((today or date.today().isoformat())[:10])
        data = self.lookup_namespace(namespace)
        by_type: dict[str, list[dict[str, Any]]] = {}
        for ent in data["entities"]:
            obs_str = str(ent.get("last_observed_at") or "")[:10]
            try:
                obs_d = date.fromisoformat(obs_str)
                age_days = max(0, (today_d - obs_d).days)
            except ValueError:
                age_days = 0
            state = "fresh" if age_days <= 90 else ("aging" if age_days <= 365 else "stale")
            by_type.setdefault(ent["entity_type"], []).append(
                {
                    "id": ent["id"],
                    "name": ent["name"],
                    "observed_at": obs_str,
                    "age_days": age_days,
                    "state": state,
                }
            )
        return {"namespace": data["namespace"], "by_type": by_type}

    def ingest_from_project(self, project_id: str, repos: Any, namespace: str = "") -> dict[str, int]:
        """Ingest accepted evidence entities and attributes from a project into the global KB."""
        from research_engine.models.enums import EvidenceStatus

        proj = repos.projects.get(project_id)
        ns = (namespace or (f"{proj.mode}:global" if proj else "generic:global")).strip().lower()
        evs = [
            e for e in repos.evidence.all(project_id)
            if e.status != EvidenceStatus.REJECTED
        ]
        ent_count = 0
        obs_count = 0
        for ev in evs:
            for raw_ent in ev.entities:
                if not raw_ent or not raw_ent.strip():
                    continue
                ent = self.upsert_entity(
                    namespace=ns,
                    entity_type="named_entity",
                    natural_key=raw_ent,
                    name=raw_ent.strip(),
                    attributes=ev.attributes or {},
                    project_id=project_id,
                    observed_at=ev.retrieved_at or _now_iso(),
                )
                ent_count += 1
                self.record_observation(
                    entity_id=ent["id"],
                    project_id=project_id,
                    evidence_id=ev.id,
                    claim_text=ev.claim_text,
                    quote=ev.quote,
                    source_url=ev.source_url,
                    source_tier=ev.source_tier,
                    observed_at=ev.retrieved_at or _now_iso(),
                    data={"attributes": ev.attributes or {}, "tags": ev.tags},
                )
                obs_count += 1
        return {"entities_upserted": ent_count, "observations_recorded": obs_count}

    def seed_project_from_kb(
        self,
        project_id: str,
        repos: Any,
        namespace: str,
        use_global_kb: bool = False,
    ) -> int:
        """Seed a project with prior observations from `namespace` ONLY when `use_global_kb=True`.

        Enforces INV-013: cross-project memory never leaks into a project unless
        explicitly requested via `use_global_kb=True`.
        """
        if not use_global_kb:
            return 0
        from research_engine.models.enums import ClaimKind, ContentStatus, EvidenceStatus, SourceType
        from research_engine.models.evidence import Evidence
        from research_engine.models.research import Source

        bundle = self.lookup_namespace(namespace)
        if not bundle["observations"]:
            return 0

        existing_quotes = {e.quote for e in repos.evidence.all(project_id)}
        seeded = 0
        for obs in bundle["observations"]:
            if obs["project_id"] == project_id or obs["quote"] in existing_quotes:
                continue
            url = obs["source_url"] or f"kb://{bundle['namespace']}/{obs['entity_id']}"
            src = repos.sources.find_by_canonical_url(project_id, url)
            if src is None:
                src = Source(
                    project_id=project_id,
                    url=url,
                    canonical_url=url,
                    title=f"Global KB ({bundle['namespace']})",
                    domain="relational_kb",
                    source_type=SourceType.INTERNAL_DATA,
                    source_tier=max(2, int(obs.get("source_tier", 3))),
                    content_status=ContentStatus.PARSED.value,
                )
                src.ensure_id()
                repos.sources.save(src)
            ev = Evidence(
                project_id=project_id,
                claim_text=obs["claim_text"],
                quote=obs["quote"] or obs["claim_text"],
                source_id=src.id,
                location=f"relational_kb:{obs['entity_id']}",
                source_url=url,
                source_title=src.title,
                source_type=SourceType.INTERNAL_DATA,
                source_tier=src.source_tier,
                retrieved_at=obs["observed_at"],
                confidence=0.75,
                status=EvidenceStatus.SUPPORTED,
                kind=ClaimKind.FACT,
                validation_notes=f"seeded from relational_kb ({obs['project_id']})",
                support_verdict="ENTAILS",
                support_score=0.9,
                extracted_by="relational_kb",
                attributes=(obs.get("data") or {}).get("attributes", {}),
            )
            ev.ensure_id()
            repos.evidence.save(ev)
            existing_quotes.add(ev.quote)
            seeded += 1
        return seeded

    @staticmethod
    def _row_to_entity(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["attributes"] = json.loads(d.get("attributes") or "{}")
        return d
