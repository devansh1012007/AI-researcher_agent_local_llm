"""Regression tests for BUG-07 (FTS duplication), BUG-11 (silent event
drops), BUG-12 (project.json ghost listings)."""
from __future__ import annotations

QUESTION = "Does retrieval augmented generation improve factuality of answers?"

import json
import tempfile
import pathlib

import pytest


class TestFtsLifecycle:
    def test_re_save_never_duplicates_fts_rows(self):
        import tempfile, pathlib
        from research_engine.models.evidence import Evidence
        from research_engine.storage.database import Database
        from research_engine.storage.repositories import Repositories
        db = Database(pathlib.Path(tempfile.mkdtemp()) / "t.sqlite")
        r = Repositories(db)
        e = Evidence(project_id="p", claim_text="grounding reduces hallucinations",
                     quote="grounding reduces hallucinations", source_id="s",
                     status="EXTRACTED")
        e.ensure_id()
        for _ in range(3):
            r.evidence.save(e)
        fts = db.execute("SELECT COUNT(*) FROM evidence_fts")[0][0]
        ev = db.execute("SELECT COUNT(*) FROM evidence")[0][0]
        assert ev == 1 and fts == 1, f"ev={ev} fts={fts}"
        hits = db.fts_search("p", "hallucinations")
        assert len(hits) == 1


class TestEventBusAccounting:
    def test_drops_are_counted_and_logged(self, caplog):
        from research_engine.platform.events import DomainEvent, EventBus
        bus = EventBus(queue_size=4)
        _sid, q = bus.subscribe(None)
        for i in range(20):
            bus.publish(DomainEvent(type=f"t{i}", project_id="p", payload={}))
        drained = 0
        while True:
            try:
                q.get_nowait()
                drained += 1
            except Exception:
                break
        assert bus.dropped_events == 20 - drained > 0


class TestProjectGhosts:
    def test_ghost_workspace_excluded_from_listing(self, tmp_path):
        from research_engine.services.context import ServiceContext
        from research_engine.services.research_service import ProjectService
        ctx = ServiceContext(data_dir=str(tmp_path))
        svc = ProjectService(ctx)
        from research_engine.services.research_service import ProjectCreate
        created = svc.create(ProjectCreate(question=QUESTION + " about grounding",
                                           mode="academic"))
        # forge a ghost: project.json without DB row
        ghost = tmp_path / "proj_ghost"
        (ghost / "reports").mkdir(parents=True)
        (ghost / "project.json").write_text(json.dumps(
            {"id": "proj_ghost", "question_raw": "ghost", "mode": "academic"}))
        listed = [p["id"] for p in svc.list_projects()]
        assert created["id"] in listed
        assert "proj_ghost" not in listed
        with pytest.raises(Exception):
            svc.get("proj_ghost")
