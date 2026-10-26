"""Golden equivalence test for academic and startup modes / engine packs."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from research_engine.models.enums import ContentStatus, EvidenceStatus, SourceType
from research_engine.models.evidence import Claim, Evidence
from research_engine.models.project import ResearchProject
from research_engine.models.research import Source
from research_engine.modes.base import get_mode
from research_engine.pipeline.clarification import ClarificationWorker
from research_engine.pipeline.planning import PlannerWorker
from research_engine.pipeline.routing import route_for
from research_engine.providers.llm.base import MockProvider
from research_engine.reasoning.structural_gaps import StructuralGapDetector
from research_engine.storage.database import Database
from research_engine.storage.repositories import Repositories

SNAPSHOT_PATH = Path(__file__).parent / "mode_snapshot.json"


def _capture_current() -> dict:
    snapshot = {}
    for mode_name in ("academic", "startup"):
        m = get_mode(mode_name)
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "project.db")
            repos = Repositories(db)
            p = ResearchProject(
                id="proj_1",
                mode=mode_name,
                question_raw="Will AI tutoring replace coding bootcamps?",
            )
            repos.projects.save(p)
            llm = MockProvider(handler=lambda s, u: "")
            clarifier = ClarificationWorker(llm, repos)
            pd = clarifier.run("proj_1", p.question_raw, mode_name)
            planner = PlannerWorker(llm, repos, mode_name)
            plan = planner.run("proj_1", pd)
            src = Source(
                id="src_1",
                project_id="proj_1",
                url="https://example.com/a",
                canonical_url="https://example.com/a",
                domain="example.com",
                title="Example",
                source_type=SourceType.BLOG,
                source_tier=4,
                content_status=ContentStatus.PARSED.value,
            )
            repos.sources.save(src)
            for idx in range(3):
                ev = Evidence(
                    id=f"ev_{idx+1}",
                    project_id="proj_1",
                    claim_text=f"AI tutoring improves learning speed by {10 + idx}% in early trials.",
                    quote=f"AI tutoring improves learning speed by {10 + idx}% in early trials.",
                    source_id="src_1",
                    document_id="doc_1",
                    chunk_id="chk_1",
                    source_url="https://example.com/a",
                    source_title="Example",
                    source_type=SourceType.BLOG,
                    source_tier=4,
                    status=EvidenceStatus.SUPPORTED,
                )
                repos.evidence.save(ev)
            clm = Claim(
                id="clm_1",
                project_id="proj_1",
                text="AI tutoring improves test scores by 20% compared to baseline.",
                branch=plan.branches[0].id,
                confidence=0.8,
                supported_by=["ev_1"],
            )
            repos.claims.save(clm)
            sg_gaps = StructuralGapDetector(repos).detect("proj_1", mode=mode_name)
            snapshot[mode_name] = {
                "mode_dataclass": {
                    "name": m.name,
                    "display_name": m.display_name,
                    "branch_categories": m.branch_categories,
                    "source_preferences": m.source_preferences,
                    "evidence_schema_hint": m.evidence_schema_hint,
                    "report_files": m.report_files,
                },
                "routes": {
                    cat: [leg.name for leg in route_for(cat).legs]
                    for cat in m.branch_categories
                },
                "fallback_plan": [
                    {
                        "category": b.category.value if hasattr(b.category, "value") else str(b.category),
                        "question": b.question,
                        "importance": b.importance,
                        "required_evidence": b.required_evidence,
                        "source_preferences": b.source_preferences,
                    }
                    for b in plan.branches
                ],
                "structural_gaps_seeded": [
                    {
                        "category": g.category.value if hasattr(g.category, "value") else str(g.category),
                        "severity": g.severity.value if hasattr(g.severity, "value") else str(g.severity),
                        "description": g.description,
                        "importance": g.importance,
                        "evidence_needed": g.evidence_needed,
                    }
                    for g in sg_gaps
                ],
            }
    return snapshot


def test_mode_equivalence_matches_golden_snapshot():
    expected = json.loads(SNAPSHOT_PATH.read_text())
    actual = _capture_current()
    assert actual == expected
