"""End-to-end tests for all 3 ways of adding the 'example_researcher' agent to GAR."""
from __future__ import annotations

import json
from pathlib import Path

from research_engine.core.config import AppConfig
from research_engine.core.orchestrator import Orchestrator
from research_engine.engines.loader import (
    diff_engines,
    engine_names,
    explain_engine,
    get_engine,
    load_engine_from_dir,
    reload,
    scaffold_engine,
    validate_engine_target,
)
from research_engine.models.document import Document, DocumentChunk
from research_engine.models.enums import ContentStatus, EvidenceStatus, SourceType
from research_engine.models.research import Source
from research_engine.pipeline.evidence import EvidenceWorker
from research_engine.pipeline.planning import PlannerWorker
from research_engine.pipeline.routing import route_for
from research_engine.prompts.registry import get_prompt
from research_engine.providers.llm.base import MockProvider

REPO_ROOT = Path(__file__).parents[2]


def test_way_1_builtin_example_researcher_end_to_end(tmp_path: Path):
    """Way 1: Built-in pack under src/research_engine/engines/builtin/example_researcher/."""
    reload()
    assert "example_researcher" in engine_names()
    manifest, warnings = validate_engine_target("example_researcher")
    assert warnings == []
    assert manifest.name == "example_researcher"
    assert manifest.source_layer == "builtin"
    assert manifest.branch_categories() == [
        "EXAMPLE_ALPHA",
        "EXAMPLE_BETA",
        "EXAMPLE_JIBRISH",
        "EXAMPLE_WIDGETS",
    ]
    assert [s.name for s in manifest.skills] == [
        "example_discovery",
        "example_planning_jibrish",
        "example_jibrish_rules",
    ]
    assert "example_target_widget" in manifest.guidance_for("clarify")
    assert "zibbles/sec" in manifest.guidance_for("plan")

    # Pack-local prompt overlay is active
    extractor_spec = get_prompt("evidence_extractor", engine="example_researcher")
    assert "[EXAMPLE RESEARCHER EXTRACTOR - WAY 1 BUILTIN]" in extractor_spec.template

    # End-to-end orchestrator + planner + evidence extraction with jibrish schema attributes
    cfg = AppConfig()
    cfg.storage.data_dir = str(tmp_path / "data_way1")
    orch = Orchestrator.create_project(
        cfg,
        "Investigate Florb-X9 zibble throughput and snorf anomalies",
        mode="example_researcher",
    )
    orch._phase_clarify()
    questions = orch.repos.questions.all(orch.project.id)
    assert any("example_target_widget" in q.text for q in questions)

    problem = orch.repos.problems.all(orch.project.id)[0]
    planner = PlannerWorker(MockProvider(handler=lambda s, u: ""), orch.repos, "example_researcher")
    plan = planner.run(orch.project.id, problem)
    assert [b.category for b in plan.branches] == [
        "EXAMPLE_ALPHA",
        "EXAMPLE_BETA",
        "EXAMPLE_JIBRISH",
    ]

    src = Source(
        id="src_ex1",
        project_id=orch.project.id,
        url="https://example.com/florb-x9",
        canonical_url="https://example.com/florb-x9",
        domain="example.com",
        title="Florb-X9 Jibrish Telemetry",
        source_type=SourceType.DOCUMENTATION,
        source_tier=1,
        content_status=ContentStatus.PARSED.value,
    )
    orch.repos.sources.save(src)
    doc = Document(
        id="doc_ex1",
        project_id=orch.project.id,
        source_id=src.id,
        url=src.url,
        title=src.title,
        text="Florb-X9 achieves 420 zibbles per second with a jibrish score of 88.5 in alpha_florb mode.",
        content_status=ContentStatus.PARSED.value,
        word_count=16,
    )
    orch.repos.documents.save(doc)
    orch.repos.chunks.save(
        DocumentChunk(
            id="chk_ex1",
            project_id=orch.project.id,
            document_id=doc.id,
            sequence=0,
            text=doc.text,
        )
    )

    def _fake_extractor(system: str, user: str) -> str:
        return json.dumps({
            "evidence": [
                {
                    "claim": "Florb-X9 achieves 420 zibbles per second with a jibrish score of 88.5 in alpha_florb mode.",
                    "quote": "Florb-X9 achieves 420 zibbles per second with a jibrish score of 88.5 in alpha_florb mode.",
                    "confidence": 0.92,
                    "entities": ["Florb-X9"],
                    "tags": ["florb", "jibrish"],
                    "kind": "FACT",
                    "numbers": [],
                    "attributes": {
                        "example_widget_id": "FLORB-X9",
                        "jibrish_score": 88.5,
                        "florb_category": "alpha_florb",
                        "example_metric_note": "verified wumpus baseline",
                    },
                }
            ]
        })

    ev_worker = EvidenceWorker(orch.cfg, MockProvider(handler=_fake_extractor), orch.repos)
    evs, rej = ev_worker.extract_from_documents(
        orch.project.id, [doc], "What is Florb-X9 throughput?", iteration=1, mode="example_researcher"
    )
    assert rej == 0
    assert len(evs) == 1
    assert evs[0].status != EvidenceStatus.REJECTED
    assert evs[0].attributes["example_widget_id"] == "FLORB-X9"
    assert evs[0].attributes["jibrish_score"] == 88.5
    assert evs[0].attributes["florb_category"] == "alpha_florb"


def test_way_2_workspace_and_path_example_researcher():
    """Way 2: External/workspace directory pack under ./engines/example_researcher_workspace/ or loaded by path."""
    reload()
    pack_path = REPO_ROOT / "engines" / "example_researcher_workspace"
    assert pack_path.is_dir()

    # Discovered automatically from ./engines/ (workspace layer)
    manifest = get_engine("example_researcher_workspace")
    assert manifest.name == "example_researcher_workspace"
    assert manifest.source_layer == "workspace"
    assert manifest.extends == "generic"
    assert manifest.branch_categories() == [
        "EXAMPLE_SPROCKETS",
        "JIBRISH_QUX_FLOW",
        "EXAMPLE_FOOBAR_GAPS",
    ]
    route = route_for("EXAMPLE_FOOBAR_GAPS", engine="example_researcher_workspace")
    assert [leg.name for leg in route.legs] == ["forum", "web", "documentation"]

    # Also loadable directly by filesystem path (path layer)
    by_path = load_engine_from_dir(pack_path)
    assert by_path.name == "example_researcher_workspace"
    assert by_path.source_layer == "path"


def test_way_3_inherited_and_scaffolded_example_researcher(tmp_path: Path):
    """Way 3: Inherited/scaffolded pack extending 'example_researcher' via extends + scaffold_engine."""
    reload()
    inherited = get_engine("example_researcher_inherited")
    assert inherited.name == "example_researcher_inherited"
    assert inherited.extends == "example_researcher"
    # Inherits all 4 branches from example_researcher
    assert inherited.branch_categories() == [
        "EXAMPLE_ALPHA",
        "EXAMPLE_BETA",
        "EXAMPLE_JIBRISH",
        "EXAMPLE_WIDGETS",
    ]
    # Overrides tunables and required_inputs
    assert inherited.tunables.max_iterations == 4
    assert inherited.tunables.max_queries_per_iteration == 10
    assert "turbo_wumpus_seed" in inherited.clarifier.required_inputs
    assert "turbo_wumpus_mode" in inherited.domain_schema_dict["properties"]

    # Explain and diff between base and inherited example researcher packs
    exp = explain_engine("example_researcher_inherited", include_vars=True)
    assert exp["extends"] == "example_researcher"
    diff = diff_engines("example_researcher", "example_researcher_inherited")
    assert "tunables" in diff["differences"]

    # Also verify programmatic scaffolding (`research engine new ... --extends example_researcher`)
    scaff_dir = scaffold_engine(
        "example_researcher_scaffold",
        target_root=tmp_path / "custom_engines",
        extends="example_researcher",
    )
    scaff_manifest, warnings = validate_engine_target(scaff_dir)
    assert warnings == []
    assert scaff_manifest.extends == "example_researcher"
    assert scaff_manifest.branch_categories() == [
        "EXAMPLE_ALPHA",
        "EXAMPLE_BETA",
        "EXAMPLE_JIBRISH",
        "EXAMPLE_WIDGETS",
    ]
