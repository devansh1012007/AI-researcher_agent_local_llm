"""Acceptance test for third-party engine pack (`product_teardown`) with zero core code changes (Phase 10)."""
from __future__ import annotations

import json
from pathlib import Path

from research_engine.core.config import AppConfig
from research_engine.core.orchestrator import Orchestrator
from research_engine.engines.loader import (
    clear_search_dirs,
    get_engine,
    register_search_dir,
)
from research_engine.mcp_server.server import build_tools
from research_engine.models.document import Document, DocumentChunk
from research_engine.models.enums import ContentStatus, EvidenceStatus, SourceType
from research_engine.models.research import Source
from research_engine.pipeline.evidence import EvidenceWorker
from research_engine.pipeline.planning import PlannerWorker
from research_engine.pipeline.routing import route_for
from research_engine.providers.llm.base import MockProvider
from research_engine.services.research_service import ProjectCreate

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_third_party_product_teardown_pack_end_to_end(tmp_path: Path):
    try:
        register_search_dir(FIXTURES_DIR)
        manifest = get_engine("product_teardown")
        assert manifest.extends == "generic"
        assert manifest.branch_categories() == [
            "ONBOARDING", "CORE_LOOP", "PRICING", "RETENTION", "WEAKNESSES"
        ]

        # 1. Dynamic vocabulary in ProjectCreate and MCP build_tools
        dto = ProjectCreate(
            question="Teardown Figma onboarding, core loop, and pricing tiers",
            mode="product_teardown",
        )
        assert dto.mode == "product_teardown"
        create_tool = next(t for t in build_tools() if t["name"] == "create_research_project")
        assert "product_teardown" in create_tool["inputSchema"]["properties"]["mode"]["enum"]

        # 2. Custom category routing from engine.yaml
        r_pricing = route_for("PRICING", engine="product_teardown")
        assert [leg.name for leg in r_pricing.legs] == ["web", "company"]
        r_onb = route_for("ONBOARDING", engine="product_teardown")
        assert [leg.name for leg in r_onb.legs] == ["web", "documentation", "forum"]

        # 3. Orchestrator project creation, effective tunables, and required_input question generation
        cfg = AppConfig()
        cfg.storage.data_dir = str(tmp_path / "data")
        orch = Orchestrator.create_project(
            cfg,
            "Analyze Notion's onboarding flow, core loop, and pricing model",
            mode="product_teardown",
        )
        assert orch.cfg.research.max_iterations == 2
        assert orch.cfg.research.max_queries_per_iteration == 6
        assert orch.cfg.search.results_per_query == 5

        orch._phase_clarify()
        questions = orch.repos.questions.all(orch.project.id)
        assert len(questions) >= 1
        assert any("target_product" in q.text for q in questions)
        assert all(q.changes.strip() for q in questions)

        # 4. Fallback plan uses the 5 product_teardown categories
        problem = orch.repos.problems.all(orch.project.id)[0]
        planner = PlannerWorker(MockProvider(handler=lambda s, u: ""), orch.repos, "product_teardown")
        plan = planner.run(orch.project.id, problem)
        assert [b.category for b in plan.branches] == [
            "ONBOARDING", "CORE_LOOP", "PRICING", "RETENTION", "WEAKNESSES"
        ]

        # 5. Evidence extraction uses pack prompt overlay and validates domain attributes field-by-field
        src = Source(
            id="src_td1",
            project_id=orch.project.id,
            url="https://example.com/notion-pricing",
            canonical_url="https://example.com/notion-pricing",
            domain="example.com",
            title="Notion Teardown",
            source_type=SourceType.COMPANY,
            source_tier=2,
            content_status=ContentStatus.PARSED.value,
        )
        orch.repos.sources.save(src)
        doc = Document(
            id="doc_td1",
            project_id=orch.project.id,
            source_id=src.id,
            url=src.url,
            title=src.title,
            text="Notion Plus plan costs $10 per seat per month and requires workspace setup during onboarding.",
            content_status=ContentStatus.PARSED.value,
            word_count=16,
        )
        orch.repos.documents.save(doc)
        chk = DocumentChunk(
            id="chk_td1",
            project_id=orch.project.id,
            document_id=doc.id,
            sequence=0,
            text=doc.text,
        )
        orch.repos.chunks.save(chk)

        captured_prompts: list[str] = []

        def _fake_extractor(system: str, user: str) -> str:
            captured_prompts.append(user)
            return json.dumps({
                "evidence": [
                    {
                        "claim": "Notion Plus plan costs $10 per seat per month and requires workspace setup during onboarding.",
                        "quote": "Notion Plus plan costs $10 per seat per month and requires workspace setup during onboarding.",
                        "confidence": 0.9,
                        "entities": ["Notion"],
                        "tags": ["pricing", "onboarding"],
                        "kind": "FACT",
                        "numbers": [],
                        "attributes": {
                            "ux_step": "workspace setup",
                            "friction_level": "invalid_enum_value",
                            "pricing_tier": "Plus ($10/seat/mo)",
                        },
                    }
                ]
            })

        ev_worker = EvidenceWorker(orch.cfg, MockProvider(handler=_fake_extractor), orch.repos)
        evs, rej = ev_worker.extract_from_documents(
            orch.project.id, [doc], "How is Notion priced?", iteration=1, mode="product_teardown"
        )
        assert rej == 0
        assert len(evs) == 1
        assert "[PRODUCT TEARDOWN EXTRACTOR]" in captured_prompts[0]
        ev = evs[0]
        assert ev.status != EvidenceStatus.REJECTED
        # Valid attributes kept; invalid enum attribute dropped with validation note!
        assert ev.attributes == {
            "ux_step": "workspace setup",
            "pricing_tier": "Plus ($10/seat/mo)",
        }
        assert "dropped attribute 'friction_level'" in ev.validation_notes
    finally:
        clear_search_dirs()


def test_custom_pack_cli_option(request, tmp_path: Path):
    """Appendix C support: `pytest tests/engines/test_third_party_pack.py --pack <path>`."""
    import os
    import sys
    from research_engine.engines.loader import validate_engine_target
    pack_opt = ""
    if hasattr(request, "config"):
        pack_opt = request.config.getoption("--pack", default="")
    if not pack_opt and "--pack" in sys.argv:
        idx = sys.argv.index("--pack")
        if idx + 1 < len(sys.argv):
            pack_opt = sys.argv[idx + 1]
    if not pack_opt:
        pack_opt = os.environ.get("GAR_TEST_PACK", "")
    target = Path(pack_opt) if pack_opt else (FIXTURES_DIR / "product_teardown")
    manifest, warnings = validate_engine_target(target)
    assert manifest.name
    assert len(manifest.branch_categories()) >= 1
