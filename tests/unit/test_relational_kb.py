"""Unit tests for Phase 8 Cross-Project Relational Memory (`memory/relational_kb.py`)."""
from __future__ import annotations

from pathlib import Path

from research_engine.memory.relational_kb import RelationalKnowledgeBase
from research_engine.models.enums import EvidenceStatus, SourceType
from research_engine.models.evidence import Evidence
from research_engine.models.project import ResearchProject
from research_engine.specialists.startup.kb import MarketKnowledgeBase
from research_engine.specialists.startup.models import (
    CompetitorProfile,
    DistributionChannel,
    Market,
    PricingPlan,
)
from research_engine.storage.database import Database
from research_engine.storage.repositories import Repositories


def test_relational_kb_entity_idempotency_observations_and_relations(tmp_path: Path):
    rkb = RelationalKnowledgeBase(tmp_path)

    # 1. Upsert entity idempotently by (namespace, entity_type, natural_key) (INV-003)
    e1 = rkb.upsert_entity(
        namespace="academic:solid_state",
        entity_type="dataset",
        natural_key="MatBench-v1",
        name="MatBench v1",
        attributes={"samples": 1000},
        project_id="proj_1",
        observed_at="2026-10-01T00:00:00Z",
    )
    e2 = rkb.upsert_entity(
        namespace="academic:solid_state",
        entity_type="dataset",
        natural_key="matbench-v1",
        name="MatBench v1.1",
        attributes={"benchmark_task": "conductivity"},
        project_id="proj_2",
        observed_at="2026-10-20T00:00:00Z",
    )
    assert e1["id"] == e2["id"]
    assert e2["attributes"]["samples"] == 1000
    assert e2["attributes"]["benchmark_task"] == "conductivity"
    assert e2["first_project_id"] == "proj_1"
    assert e2["last_project_id"] == "proj_2"

    # 2. Record observation idempotently
    obs1 = rkb.record_observation(
        entity_id=e1["id"],
        project_id="proj_1",
        evidence_id="ev_1",
        claim_text="MatBench v1 contains 1,000 solid electrolyte structures.",
        quote="MatBench v1 contains 1,000 solid electrolyte structures.",
        source_url="https://example.org/matbench",
        source_tier=1,
        observed_at="2026-10-20T00:00:00Z",
    )
    obs2 = rkb.record_observation(
        entity_id=e1["id"],
        project_id="proj_1",
        evidence_id="ev_1",
        claim_text="MatBench v1 contains 1,000 solid electrolyte structures (updated).",
        quote="MatBench v1 contains 1,000 solid electrolyte structures.",
        source_url="https://example.org/matbench",
        source_tier=1,
        observed_at="2026-10-21T00:00:00Z",
    )
    assert obs1["id"] == obs2["id"]

    # 3. Link entities
    m_ent = rkb.upsert_entity(
        namespace="academic:solid_state",
        entity_type="method",
        natural_key="cgcnn",
        name="CGCNN",
        project_id="proj_1",
    )
    rel = rkb.link_entities(
        namespace="academic:solid_state",
        from_entity_id=m_ent["id"],
        relation_type="evaluated_on",
        to_entity_id=e1["id"],
        project_id="proj_1",
        evidence_id="ev_1",
    )
    assert rel["relation_type"] == "evaluated_on"

    bundle = rkb.lookup_namespace("academic:solid_state")
    assert len(bundle["entities"]) == 2
    assert len(bundle["observations"]) == 1
    assert len(bundle["relations"]) == 1

    fresh = rkb.freshness_summary("academic:solid_state", today="2026-10-25")
    assert fresh["by_type"]["dataset"][0]["state"] == "fresh"


def test_relational_kb_project_isolation_and_opt_in_seeding_inv_013(tmp_path: Path):
    rkb = RelationalKnowledgeBase(tmp_path)

    # Project A ingests evidence into global KB
    db_a = Database(tmp_path / "proj_a" / "db.sqlite")
    repos_a = Repositories(db_a)
    pa = ResearchProject(id="proj_a", question_raw="Battery study A", mode="academic")
    repos_a.projects.save(pa)
    ev_a = Evidence(
        id="ev_a1",
        project_id="proj_a",
        claim_text="LLZO garnet electrolytes achieve 1 mS/cm conductivity at 25C.",
        quote="LLZO garnet electrolytes achieve 1 mS/cm conductivity at 25C.",
        source_id="src_a1",
        source_url="https://example.org/llzo",
        source_tier=1,
        entities=["LLZO"],
        status=EvidenceStatus.SUPPORTED,
        attributes={"method_or_model": "LLZO"},
    )
    repos_a.evidence.save(ev_a)
    stats = rkb.ingest_from_project("proj_a", repos_a, namespace="academic:global")
    assert stats["entities_upserted"] == 1
    assert stats["observations_recorded"] == 1

    # Project B with use_global_kb=False (default) MUST receive 0 seeded items (INV-013)
    db_b = Database(tmp_path / "proj_b" / "db.sqlite")
    repos_b = Repositories(db_b)
    pb = ResearchProject(id="proj_b", question_raw="Battery study B", mode="academic")
    repos_b.projects.save(pb)

    seeded_default = rkb.seed_project_from_kb("proj_b", repos_b, "academic:global", use_global_kb=False)
    assert seeded_default == 0
    assert repos_b.evidence.count("proj_b") == 0

    # When explicitly opted in (use_global_kb=True), Project B receives the observation
    seeded_opt_in = rkb.seed_project_from_kb("proj_b", repos_b, "academic:global", use_global_kb=True)
    assert seeded_opt_in == 1
    assert repos_b.evidence.count("proj_b") == 1
    # Calling seed again is idempotent
    assert rkb.seed_project_from_kb("proj_b", repos_b, "academic:global", use_global_kb=True) == 0


def test_market_kb_mirrors_entities_and_relations_to_relational_kb(tmp_path: Path):
    mkb = MarketKnowledgeBase(tmp_path)
    mkt = Market(project_id="proj_s1", name="AI Bookkeeping India", market_slug="ai-bookkeeping-india")
    comp = CompetitorProfile(project_id="proj_s1", name="Zoho Books", classification="direct")
    plan = PricingPlan(project_id="proj_s1", competitor_name="Zoho Books", price_raw="$15", billing_period="monthly")
    chan = DistributionChannel(project_id="proj_s1", name="CA Partner Network")

    mkb.remember_market(mkt, competitors=[comp], pricing_plans=[plan], channels=[chan])

    bundle = mkb.relational_kb.lookup_namespace("startup:ai-bookkeeping-india")
    types = {e["entity_type"] for e in bundle["entities"]}
    assert types == {"market", "competitor", "pricing_plan", "distribution_channel"}
    rel_types = {r["relation_type"] for r in bundle["relations"]}
    assert rel_types == {"operates_in", "offers_plan", "uses_channel"}
