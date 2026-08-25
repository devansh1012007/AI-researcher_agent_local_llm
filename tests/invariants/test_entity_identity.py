"""BUG-02 reproduction + idempotency invariant (INVARIANT-003)."""
import pathlib
import sqlite3
import tempfile

import pytest


@pytest.fixture()
def seeded_project(tmp_path):
    from research_engine.core.config import AppConfig
    from research_engine.core.orchestrator import Orchestrator
    cfg = AppConfig.load()
    cfg.storage.data_dir = str(tmp_path)
    cfg.search.web_provider = "none"
    cfg.search.academic_providers = []
    Q = ("Find promising startup opportunities in AI bookkeeping "
         "software for Indian SMB retailers")
    orch = Orchestrator.create_project(cfg, Q, mode="startup")
    pid = orch.project.id
    from research_engine.models.evidence import Evidence
    from research_engine.models.research import Source
    s = Source(project_id=pid, url="https://f.example.com/1",
               canonical_url="https://f.example.com/1",
               domain="f.example.com", title="t")
    s.ensure_id()
    orch.repos.sources.save(s)
    for claim in ["Retailers complain bookkeeping is manual and time-consuming weekly",
                  "Shop owners paying accountants 15000 rupees per month",
                  "Zoho Books charges 15 dollars per month"]:
        e = Evidence(project_id=pid, claim_text=claim, quote=claim[:40],
                     source_id=s.id, source_tier=4, status="EXTRACTED")
        e.ensure_id()
        orch.repos.evidence.save(e)
    from research_engine.storage.graph_store import GraphEntity, GraphStore
    GraphStore(orch.db).upsert_entity(GraphEntity(
        project_id=pid, type="competitor", name="Zoho Books",
        attributes={"product": "accounting software", "positioning": "smb"}))
    return orch, cfg, tmp_path, pid


TABLES = ["startup_markets", "competitor_profiles", "pricing_plans",
          "startup_personas", "alternatives", "jtbd", "opportunity_decisions"]


def _counts(db_path):
    conn = sqlite3.connect(db_path)
    return {t: conn.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
            for t in TABLES}


class TestBug02Idempotency:
    def test_original_repro_now_converges(self, seeded_project):
        """ORIGINAL AUDIT REPRO: three consecutive full pipelines.
        Before the fix counts grew every run; now they must converge."""
        orch, cfg, tmp, pid = seeded_project
        from research_engine.specialists.startup.service import StartupResearchService
        svc = StartupResearchService(cfg=cfg, data_dir=str(tmp))
        svc.run_full_pipeline(pid)
        c1 = _counts(orch.ws.db_path)
        assert any(v > 0 for v in c1.values()), "pipeline produced entities"
        svc.run_full_pipeline(pid)
        c2 = _counts(orch.ws.db_path)
        svc.run_full_pipeline(pid)
        c3 = _counts(orch.ws.db_path)
        # INVARIANT-003: repeated analysis is idempotent
        assert c2 == c3, f"rows still growing: {c2} -> {c3}"
        for t in TABLES:
            assert c3[t] <= max(c1[t], 1), f"{t} grew across runs"

    def test_natural_key_resolution_keeps_identity(self, tmp_path):
        """Same natural key -> same entity id, merged provenance.
        Unique indexes are DROPPED so ONLY the application resolver can
        provide identity (kills mutation M-4 which disabled resolution)."""
        from research_engine.storage.database import Database
        from research_engine.specialists.startup.models import CompetitorProfile
        from research_engine.specialists.startup.repos import StartupRepos
        db = Database(pathlib.Path(tmp_path) / "t.sqlite")
        db._conn().execute("DROP INDEX IF EXISTS ux_competitors_name")
        repos = StartupRepos(db)
        a = CompetitorProfile(project_id="p", name="OpenAI",
                              product="gpt platform")
        a.ensure_id()
        saved1 = repos.competitor_profiles.save_natural(a)
        b = CompetitorProfile(project_id="p", name="openai, inc.",
                              strengths=["research"], evidence_ids=["ev_1"])
        b.ensure_id()
        saved2 = repos.competitor_profiles.save_natural(b)
        assert saved2.id == saved1.id, "natural identity must be preserved"
        rows = repos.competitor_profiles.all("p")
        assert len(rows) == 1
        assert rows[0].strengths == ["research"]
        assert rows[0].evidence_ids == ["ev_1"]

    def test_data_repair_dedupes_legacy_pollution(self, tmp_path):
        """Repair tool on a pre-fix polluted DB: dedupe by natural key,
        merge provenance into canonical row, complete unique indexes."""
        from research_engine.specialists.startup.models import CompetitorProfile
        from research_engine.specialists.startup.repos import StartupRepos
        from research_engine.specialists.startup.data_repair import repair_project
        from research_engine.storage.database import Database
        db = Database(pathlib.Path(tmp_path) / "t.sqlite")
        repos = StartupRepos(db)
        # simulate legacy DB: drop the unique index, then pollute
        db._conn().execute("DROP INDEX IF EXISTS ux_competitors_name")
        import json as _json
        for i, name in enumerate(["Acme", "acme", "ACME Corp", "Other"]):
            e = CompetitorProfile(project_id="p", name=name)
            e.id = f"cpx_test{i:03d}"
            db.upsert("competitor_profiles", e.id, "p",
                      _json.loads(e.model_dump_json()),
                      {"name_lower": name.lower(), "classification": ""})
        before = len(repos.competitor_profiles.all("p"))
        assert before == 4
        summary = repair_project(db)
        after_rows = repos.competitor_profiles.all("p")
        names = {r.name.lower() for r in after_rows}
        assert len(after_rows) == 2
        assert names == {"acme", "other"}
        entry = next(t for t in summary["tables"]
                     if t["table"] == "competitor_profiles")
        assert entry["removed"] == 2

    def test_kb_seeding_idempotent(self, seeded_project):
        orch, cfg, tmp, pid = seeded_project
        from research_engine.specialists.startup.kb import MarketKnowledgeBase
        from research_engine.specialists.startup.repos import get_startup_repos
        kb = MarketKnowledgeBase(tmp)
        from research_engine.specialists.startup.models import (
            CompetitorProfile, Market)
        m = Market(project_id="kb:x", name="X", market_slug="x-market")
        m.ensure_id()
        c = CompetitorProfile(project_id="kb:x", name="Zoho Books")
        c.ensure_id()
        kb.remember_market(m, [c])
        srepos = get_startup_repos(orch)
        n1 = kb.seed_project(pid, "x-market", srepos)
        n2 = kb.seed_project(pid, "x-market", srepos)
        n3 = kb.seed_project(pid, "x-market", srepos)
        assert n1 >= 1 and n2 == 0 and n3 == 0
