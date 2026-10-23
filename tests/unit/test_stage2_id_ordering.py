"""T32 (C08/C22): ordering after the entity-id change.

Entity ids are ULIDs now, so the id TEXT is no longer a creation order:
rows written before the change keep their old `<prefix>_%06d` ids (which
sort AFTER a ULID once the counter passes 100000), the prefix differs per
entity type, and relationship ids are content hashes. Anything that needs
creation order must read the row payload's `created_at`.

Fully offline: a local SQLite file per test.
"""
import json

import pytest

from research_engine.storage.database import Database
from research_engine.storage.graph_store import (GraphEntity, GraphStore,
                                                 Relationship)

LEGACY_ID = "ent_200000"                        # old counter id
ULID_ID = "ent_01M5HC1KF2XHWHDA13EBMYNTBG"      # new ULID


@pytest.fixture()
def store(tmp_path):
    db = Database(tmp_path / "g.sqlite")
    return GraphStore(db), db


def _insert_raw_entity(db, entity_id, project_id, type_, name, name_key,
                       created_at):
    """Write a graph entity row straight to SQLite, the way a legacy row
    (written before the payload carried a timestamp) sits on disk."""
    payload = {"id": entity_id, "project_id": project_id, "type": type_,
               "name": name, "name_key": name_key, "attributes": {}}
    if created_at is not None:
        payload["created_at"] = created_at
    with db._conn() as c:
        c.execute(
            "INSERT INTO graph_entities(id, project_id, type, name_key, data) "
            "VALUES(?,?,?,?,?)",
            (entity_id, project_id, type_, name_key, json.dumps(payload)))


class TestEntityOrdering:
    def test_entities_are_oldest_first_by_payload_created_at(self, store):
        """The payload timestamp decides the order, not the id text."""
        g, db = store
        g.upsert_entity(GraphEntity(
            id=ULID_ID, project_id="p", type="company", name="Ulid Co",
            created_at="2026-01-01T00:00:00.500000Z"))
        g.upsert_entity(GraphEntity(
            id=LEGACY_ID, project_id="p", type="company", name="Legacy Co",
            created_at="2020-01-01T00:00:00Z"))
        # the ids sort the OTHER way round in SQLite BINARY order
        assert [e.id for e in g.entities("p")] == [LEGACY_ID, ULID_ID]

    def test_order_is_stable_across_repeated_calls(self, store):
        g, db = store
        for i, (eid, ts) in enumerate((
                (ULID_ID, "2026-01-02T00:00:00Z"),
                (LEGACY_ID, "2020-01-02T00:00:00Z"),
                ("ent_01M5HC1KF2XHWHDA13EBMYNTBH", "2026-01-01T00:00:00Z"))):
            g.upsert_entity(GraphEntity(id=eid, project_id="p", type="company",
                                        name=f"Co {i}", created_at=ts))
        first = [e.id for e in g.entities("p")]
        for _ in range(3):
            assert [e.id for e in g.entities("p")] == first

    def test_rows_without_a_timestamp_get_a_deterministic_position(self, store):
        """A legacy row (empty created_at) has an UNKNOWN age: it sorts
        after the rows with a known age and is tie-broken by id. The known
        row's id sorts LAST on purpose, so id-text order cannot satisfy
        this test by accident."""
        g, db = store
        g.upsert_entity(GraphEntity(id="ent_z_known", project_id="p",
                                    type="company", name="Known",
                                    created_at="2026-01-01T00:00:00Z"))
        _insert_raw_entity(db, "ent_legacy_b", "p", "company", "Legacy B",
                           "legacy b", "")
        _insert_raw_entity(db, "ent_legacy_a", "p", "company", "Legacy A",
                           "legacy a", "")
        ids = [e.id for e in g.entities("p")]
        assert ids == ["ent_z_known", "ent_legacy_a", "ent_legacy_b"]
        for _ in range(3):
            assert [e.id for e in g.entities("p")] == ids

    def test_identical_created_at_is_broken_by_id(self, store):
        """Two rows can share a timestamp to the microsecond: the tie-break
        decides, deterministically, and it is the id - not the order the
        rows were written in. The names are chosen so that neither the
        write order nor the index scan order agrees with the id order."""
        g, db = store
        g.upsert_entity(GraphEntity(id="ent_z", project_id="p", type="company",
                                    name="Alpha", created_at="2026-01-01T00:00:00Z"))
        g.upsert_entity(GraphEntity(id="ent_a", project_id="p", type="company",
                                    name="Zulu", created_at="2026-01-01T00:00:00Z"))
        assert [e.id for e in g.entities("p")] == ["ent_a", "ent_z"]

    def test_unparseable_created_at_does_not_displace_a_known_one(self, store):
        g, db = store
        g.upsert_entity(GraphEntity(id="ent_known", project_id="p",
                                    type="company", name="Known",
                                    created_at="2026-01-01T00:00:00Z"))
        g.upsert_entity(GraphEntity(id="ent_broken", project_id="p",
                                    type="company", name="Broken",
                                    created_at="not-a-timestamp"))
        assert [e.id for e in g.entities("p")] == ["ent_known", "ent_broken"]

    def test_zero_microseconds_orders_chronologically(self, store):
        """The string-comparison landmine: '...:00Z' is GREATER than
        '...:00.500000Z' as TEXT although it is the OLDER instant."""
        g, db = store
        g.upsert_entity(GraphEntity(id="ent_half", project_id="p",
                                    type="company", name="Half",
                                    created_at="2026-01-01T00:00:00.500000Z"))
        g.upsert_entity(GraphEntity(id="ent_zero", project_id="p",
                                    type="company", name="Zero",
                                    created_at="2026-01-01T00:00:00Z"))
        assert [e.id for e in g.entities("p")] == ["ent_zero", "ent_half"]

    def test_reupsert_does_not_reset_the_creation_stamp(self, store):
        """The graph builder re-upserts the same entities on every research
        cycle; the creation stamp must survive that."""
        g, db = store
        g.upsert_entity(GraphEntity(project_id="p", type="company", name="Acme"))
        first = g.entities("p")[0].created_at
        assert first, "a written entity must carry a creation stamp"
        g.upsert_entity(GraphEntity(project_id="p", type="company", name="Acme"))
        assert g.entities("p")[0].created_at == first

    def test_a_legacy_row_keeps_its_unknown_age_when_it_is_re_upserted(self, store):
        """A legacy row (no payload timestamp) must NOT be back-dated.

        Every row written before this change has an empty `created_at`, so
        its age is UNKNOWN. The next upsert used to stamp it with "now",
        which silently turned an unknown age into "newest" - the opposite
        of the truth (the row predates every row written after the
        change) and a break of the oldest-first promise `entities()`
        documents.

        The known-age row's id sorts LAST on purpose, so the legacy row
        cannot satisfy this test by id order.
        """
        g, db = store
        _insert_raw_entity(db, "ent_legacy", "p", "company", "Legacy", "legacy", "")
        # the re-upsert resolves to the legacy row (same project/type/name_key)
        g.upsert_entity(GraphEntity(id="ent_legacy", project_id="p",
                                    type="company", name="Legacy"))
        g.upsert_entity(GraphEntity(id="ent_z_known", project_id="p",
                                    type="company", name="Known",
                                    created_at="2026-01-01T00:00:00Z"))

        entities = {e.id: e for e in g.entities("p")}
        assert entities["ent_legacy"].created_at == "", (
            "the legacy row's unknown age was back-filled with a timestamp: "
            f"{entities['ent_legacy'].created_at!r}")
        assert [e.id for e in g.entities("p")] == ["ent_z_known", "ent_legacy"], (
            "the legacy row must keep sorting last - its age is unknown")


class TestRelationshipOrdering:
    @staticmethod
    def _build(path, order):
        """Create the same three edges in the given creation order."""
        db = Database(path)
        g = GraphStore(db)
        ids = {}
        for name in ("x", "y", "z"):
            ent = g.upsert_entity(GraphEntity(id=f"ent_{name}", project_id="p",
                                              type="concept", name=name))
            ids[name] = ent.id
        pairs = [(ids["x"], ids["y"], "mentions"),
                 (ids["y"], ids["z"], "supports"),
                 (ids["x"], ids["z"], "compares")]
        for i in order:
            src, tgt, rel_type = pairs[i]
            g.add_relationship(Relationship(project_id="p", source_id=src,
                                            target_id=tgt,
                                            relationship_type=rel_type))
        return g

    def test_relationship_order_is_independent_of_creation_order(self, tmp_path):
        """Relationship ids are content hashes, so the order is stable and
        does not depend on the order the edges were created in."""
        first = self._build(tmp_path / "a.sqlite", (0, 1, 2))
        second = self._build(tmp_path / "b.sqlite", (2, 1, 0))
        ids_a = [r.id for r in first.relationships("p")]
        ids_b = [r.id for r in second.relationships("p")]
        assert len(ids_a) == 3
        assert ids_a == ids_b

    def test_relationship_order_is_stable_across_repeated_calls(self, tmp_path):
        g = self._build(tmp_path / "a.sqlite", (0, 1, 2))
        first = [r.id for r in g.relationships("p")]
        for _ in range(3):
            assert [r.id for r in g.relationships("p")] == first
