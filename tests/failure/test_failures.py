"""Failure-mode tests: bad LLM output, dead sources, corrupted cache, partial writes."""
import json

import pytest
from fakes import ScriptedLLM, make_fake_transport

from research_engine.pipeline.evidence import EvidenceWorker, verify_quote
from research_engine.storage.cache import KVCache


class TestBadLLMOutput:
    def test_structured_rejects_garbage_and_reports_errors(self):
        from pydantic import BaseModel

        class Out(BaseModel):
            value: int = 0

        llm = ScriptedLLM(bad_json=True)
        model, errors = llm.structured("sys", "user", Out)
        assert model is None
        assert len(errors) == 3  # all attempts failed and were recorded
        assert llm.calls == 3

    def test_evidence_worker_survives_bad_extractions(self, cfg, tmp_path):
        from research_engine.models.document import Document, DocumentChunk
        from research_engine.models.research import Source
        from research_engine.storage.database import Database
        from research_engine.storage.repositories import Repositories

        repos = Repositories(Database(tmp_path / "t.sqlite"))
        src = Source(project_id="p", url="https://x.org", title="X")
        repos.sources.save(src)
        doc = Document(project_id="p", source_id=src.id, text="t")
        doc.ensure_id()
        repos.documents.save(doc)
        chunk = DocumentChunk(project_id="p", document_id=doc.id, sequence=0,
                              text="Some long enough chunk text with a factual claim inside it.")
        chunk.ensure_id()
        repos.chunks.save(chunk)

        worker = EvidenceWorker(cfg, ScriptedLLM(bad_json=True), repos)
        evs, rejected = worker.extract_from_documents("p", [doc], "questions", iteration=1)
        assert evs == []  # garbage output -> no evidence created, no crash


class TestSourceFailures:
    def test_failed_source_isolated(self, cfg, tmp_path):
        """One HTTP-500 source must not break processing of healthy sources."""
        from research_engine.pipeline.documents import DocumentProcessor
        from research_engine.models.research import Source
        from research_engine.storage.database import Database
        from research_engine.storage.repositories import Repositories
        from research_engine.storage.workspace import Workspace

        db = Database(tmp_path / "t.sqlite")
        repos = Repositories(db)
        ws = Workspace(tmp_path / "ws", "proj1")
        good = Source(project_id="p", url="https://good.example.org/a", title="Good")
        bad = Source(project_id="p", url="https://bad.example.org/b", title="Bad")
        for s in (good, bad):
            s.ensure_id()
            repos.sources.save(s)

        proc = DocumentProcessor(cfg, repos, ws,
                                 transport=make_fake_transport(fail_urls={"https://bad.example.org/b"}))
        docs = proc.process_sources("p", [good, bad], budget_left=5)
        assert len(docs) == 1 and docs[0].source_id == good.id
        bad_after = repos.sources.get(bad.id)
        assert bad_after.content_status == "FAILED"

    def test_duplicate_content_detected(self, cfg, tmp_path):
        """Same content under two URLs -> second is marked DUPLICATE."""
        from research_engine.pipeline.documents import DocumentProcessor
        from research_engine.models.research import Source
        from research_engine.storage.database import Database
        from research_engine.storage.repositories import Repositories
        from research_engine.storage.workspace import Workspace
        import httpx as _httpx

        def same_body(request: _httpx.Request) -> _httpx.Response:
            return _httpx.Response(200, content=b"<html><body><p>" + b"unique " * 200 +
                                   b"</p></body></html>",
                                   headers={"content-type": "text/html"})

        db = Database(tmp_path / "t.sqlite")
        repos = Repositories(db)
        ws = Workspace(tmp_path / "ws2", "proj2")
        a = Source(project_id="p", url="https://a.example.org/x", title="A")
        b = Source(project_id="p", url="https://b.example.org/y", title="B")
        for s in (a, b):
            s.ensure_id()
            repos.sources.save(s)
        transport = _httpx.MockTransport(same_body)
        proc = DocumentProcessor(cfg, repos, ws, transport=transport)
        docs = proc.process_sources("p", [a, b], budget_left=5)
        assert len(docs) == 1  # second document deduped by content hash
        statuses = {repos.sources.get(a.id).content_status,
                    repos.sources.get(b.id).content_status}
        assert statuses == {"PARSED", "DUPLICATE"}  # exactly one wins; loser marked


class TestCacheResilience:
    def test_corrupted_cache_entry_removed_not_crash(self, tmp_path):
        cache = KVCache(tmp_path / "c.sqlite")
        cache.put("seed", 1)  # ensure table exists
        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "c.sqlite"))
        conn.execute("INSERT OR REPLACE INTO cache(k, v, expires) VALUES(?,?,?)",
                     ("k", "{not json!!", None))
        conn.commit()
        conn.close()
        assert cache.get("k") is None  # returns None, cleans up
