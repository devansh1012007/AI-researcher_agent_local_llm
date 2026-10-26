"""Unit tests for TrailService, negative trail, source_trail.md, and W3C PROV-JSON export (Phase 6, INV-033)."""
from __future__ import annotations

import json
from pathlib import Path

from research_engine.models.document import Document, DocumentChunk
from research_engine.models.enums import ContentStatus, EvidenceStatus, SourceType
from research_engine.models.evidence import Claim, Evidence
from research_engine.models.project import ResearchProject, ResearchReport
from research_engine.models.research import SearchQuery, Source
from research_engine.services.trail_service import TrailService
from research_engine.storage.database import Database
from research_engine.storage.repositories import Repositories
from research_engine.storage.workspace import Workspace


def test_source_trail_lineage_negative_trail_and_prov_json(tmp_path: Path):
    ws = Workspace(tmp_path, "proj_trail")
    db = Database(ws.db_path)
    repos = Repositories(db)

    p = ResearchProject(id="proj_trail", question_raw="Test source trail", mode="academic")
    p.ensure_id()
    repos.projects.save(p)

    # 1. Query with leg_outcomes (including unconfigured) and dropped_legs
    q1 = SearchQuery(
        id="q_1",
        project_id=p.id,
        text="battery solid state dendrite suppression",
        branch="br_1",
        executed=True,
        results_count=2,
        useful_results=1,
        leg_outcomes=[
            {"leg": "openalex", "provider": "openalex", "status": "hits", "hits": 2},
            {"leg": "semantic_scholar", "provider": "semantic_scholar", "status": "optional_unconfigured", "hits": 0},
        ],
        dropped_legs=["reddit_custom"],
    )
    repos.queries.save(q1)

    # 2. One parsed source and one blocked source
    s_ok = Source(
        id="src_ok",
        project_id=p.id,
        url="https://example.org/paper1",
        canonical_url="https://example.org/paper1",
        domain="example.org",
        title="Paper 1",
        source_type=SourceType.RESEARCH_PAPER,
        source_tier=1,
        content_status=ContentStatus.PARSED.value,
        query_ids=[q1.id],
    )
    s_blocked = Source(
        id="src_blk",
        project_id=p.id,
        url="http://169.254.169.254/latest/meta-data",
        canonical_url="http://169.254.169.254/latest/meta-data",
        domain="169.254.169.254",
        title="Blocked SSRF",
        source_type=SourceType.OTHER,
        source_tier=5,
        content_status=ContentStatus.BLOCKED.value,
        rejected_reason="private/link-local IP blocked by egress policy",
        query_ids=[q1.id],
    )
    repos.sources.save(s_ok)
    repos.sources.save(s_blocked)

    # 3. Document and chunk
    doc = Document(
        id="doc_1",
        project_id=p.id,
        source_id=s_ok.id,
        url=s_ok.url,
        title=s_ok.title,
        text="Solid state electrolytes suppress lithium dendrites under 5C charging.",
        content_status=ContentStatus.PARSED.value,
        word_count=10,
    )
    repos.documents.save(doc)
    chk = DocumentChunk(
        id="chk_1",
        project_id=p.id,
        document_id=doc.id,
        sequence=0,
        text=doc.text,
        page=3,
    )
    repos.chunks.save(chk)

    # 4. One accepted evidence and one rejected evidence
    ev_ok = Evidence(
        id="ev_ok",
        project_id=p.id,
        claim_text="Solid state electrolytes suppress lithium dendrites under 5C charging.",
        quote="Solid state electrolytes suppress lithium dendrites under 5C charging.",
        source_id=s_ok.id,
        document_id=doc.id,
        chunk_id=chk.id,
        location="page 3; chunk 0",
        source_url=s_ok.canonical_url,
        source_title=s_ok.title,
        source_type=SourceType.RESEARCH_PAPER,
        source_tier=1,
        status=EvidenceStatus.SUPPORTED,
        validation_notes="exact",
        support_verdict="ENTAILS",
        extracted_by="qwen2.5:7b@ollama:evidence_extractor@v2",
        attributes={"method_or_model": "solid-state electrolyte"},
    )
    ev_rej = Evidence(
        id="ev_rej",
        project_id=p.id,
        claim_text="Hallucinated claim not in chunk.",
        quote="Fabricated quote that does not exist anywhere in the document.",
        source_id=s_ok.id,
        document_id=doc.id,
        chunk_id=chk.id,
        location="page 3; chunk 0",
        source_url=s_ok.canonical_url,
        source_title=s_ok.title,
        source_type=SourceType.RESEARCH_PAPER,
        source_tier=1,
        status=EvidenceStatus.REJECTED,
        validation_notes="quote not found in chunk (best similarity 0.21)",
        extracted_by="qwen2.5:7b@ollama:evidence_extractor@v2",
    )
    repos.evidence.save(ev_ok)
    repos.evidence.save(ev_rej)

    # 5. Claim supported by a single source
    clm = Claim(
        id="clm_1",
        project_id=p.id,
        text="Solid state electrolytes suppress lithium dendrites under 5C charging.",
        supported_by=[ev_ok.id],
        confidence=0.85,
    )
    repos.claims.save(clm)

    rep = ResearchReport(id="rep_1", project_id=p.id, kind="info", path="info.md")
    repos.reports.save(rep)

    svc = TrailService.from_repos(repos, ws, p)
    trail = svc.build_trail(p.id)

    # Forward and backward lineage verification
    assert trail["summary"]["evidence_accepted"] == 1
    assert trail["summary"]["evidence_rejected"] == 1
    assert trail["summary"]["sources_failed_or_blocked"] == 1
    assert trail["summary"]["single_source_claims"] == 1

    c_trail = svc.trail_for_claim("clm_1", p.id)
    assert c_trail["evidence_chain"][0]["evidence_id"] == "ev_ok"
    assert c_trail["evidence_chain"][0]["chunk_id"] == "chk_1"
    assert c_trail["evidence_chain"][0]["document_id"] == "doc_1"
    assert c_trail["evidence_chain"][0]["source_id"] == "src_ok"
    assert c_trail["evidence_chain"][0]["query_ids"] == ["q_1"]

    s_trail = svc.trail_for_source("src_ok", p.id)
    assert len(s_trail["evidence"]) == 2
    assert s_trail["claims"][0]["claim_id"] == "clm_1"

    # Negative trail verification (INV-033)
    neg = trail["negative_trail"]
    assert len(neg["rejected_evidence"]) == 1
    assert neg["rejected_evidence"][0]["evidence_id"] == "ev_rej"
    assert len(neg["failed_or_blocked_sources"]) == 1
    assert neg["failed_or_blocked_sources"][0]["source_id"] == "src_blk"
    assert len(neg["dropped_route_legs"]) == 1
    assert neg["dropped_route_legs"][0]["dropped_legs"] == ["reddit_custom"]
    assert len(neg["single_source_claims"]) == 1
    assert neg["single_source_claims"][0]["claim_id"] == "clm_1"

    # Markdown report & W3C PROV-JSON export
    md = svc.render_markdown(p.id)
    assert "## Claim → Evidence → Source Lineage" in md
    assert "## Negative Trail" in md
    assert "ev_rej" in md
    assert "src_blk" in md
    assert "reddit_custom" in md

    prov = svc.export_prov_json(p.id)
    out_file = ws.export_prov_json(prov)
    assert out_file.is_file()
    loaded_prov = json.loads(out_file.read_text())
    assert "gar:ev_ok" in loaded_prov["entity"]
    assert "gar:clm_1" in loaded_prov["entity"]
    assert "gar:src_ok" in loaded_prov["entity"]
    assert loaded_prov["wasDerivedFrom"]
    assert loaded_prov["wasAttributedTo"]
