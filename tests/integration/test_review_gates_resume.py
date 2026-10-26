"""Integration regression test for review gates pause and resume lifecycle (Phase 0.3 & 0.4)."""
from __future__ import annotations

from pathlib import Path

from research_engine.core.config import AppConfig
from research_engine.core.orchestrator import Orchestrator
from research_engine.models.enums import ProjectState, ReviewGate
from research_engine.pipeline.routing import ProviderRegistry
from research_engine.providers.search.base import RawSearchHit, SearchProvider


class _StubWebSearch(SearchProvider):
    name = "web"

    def __init__(self, html_by_url: dict[str, str]):
        self._urls = list(html_by_url.keys())

    def search(self, query: str, max_results: int = 5) -> list[RawSearchHit]:
        return [
            RawSearchHit(
                url=u,
                title=f"Hit for {query[:30]}",
                snippet="Empirical evaluation shows solid-state electrolytes reduce dendrite formation by 42%.",
            )
            for u in self._urls[:max_results]
        ]


def test_review_gates_pause_and_resume_reaches_completed(tmp_path: Path, monkeypatch):
    cfg = AppConfig()
    cfg.storage.data_dir = str(tmp_path / "data")
    cfg.research.review_gates_enabled = True
    cfg.research.max_iterations = 2
    cfg.research.max_queries_per_iteration = 2
    cfg.search.results_per_query = 1
    cfg.models.extractor.provider = "mock"
    cfg.models.reasoning.provider = "mock"
    cfg.models.synthesis.provider = "mock"

    html = (
        "<html><body><h1>Solid-State Battery Study</h1>"
        "<p>Empirical evaluation shows solid-state electrolytes reduce dendrite formation by 42% "
        "under 5C fast-charging conditions compared to liquid carbonate baselines.</p>"
        "</body></html>"
    )
    urls = {
        "https://example.org/study-1": html,
        "https://example.org/study-2": html,
    }

    reg = ProviderRegistry()
    reg.register_search("web", _StubWebSearch(urls))
    reg.register_academic("openalex", _StubWebSearch(urls))
    reg.register_academic("arxiv", _StubWebSearch(urls))

    orch = Orchestrator.create_project(
        cfg,
        "How do solid-state electrolytes affect dendrite formation under fast charging?",
        mode="academic",
    )
    orch.registry = reg

    def _fake_process_sources(project_id, sources, max_docs):
        from research_engine.models.document import Document, DocumentChunk
        from research_engine.models.enums import ContentStatus
        docs = []
        for s in sources[:max_docs]:
            s.content_status = ContentStatus.PARSED.value
            orch.repos.sources.save(s)
            doc = Document(
                project_id=project_id,
                source_id=s.id,
                url=s.url,
                title=s.title or "Study",
                text="Empirical evaluation shows solid-state electrolytes reduce dendrite formation by 42% under 5C fast-charging conditions.",
                content_status=ContentStatus.PARSED.value,
                word_count=18,
            )
            doc.ensure_id()
            orch.repos.documents.save(doc)
            chk = DocumentChunk(
                project_id=project_id,
                document_id=doc.id,
                sequence=0,
                text=doc.text,
            )
            chk.ensure_id()
            orch.repos.chunks.save(chk)
            docs.append(doc)
        return docs

    monkeypatch.setattr(
        orch,
        "_make_document_processor",
        lambda: type("P", (), {"process_sources": staticmethod(_fake_process_sources)})(),
    )

    # 1. Initial run pauses at AFTER_PROBLEM_DEFINITION
    p = orch.run()
    assert p.state == ProjectState.PAUSED
    assert p.review_gate_pending == ReviewGate.AFTER_PROBLEM_DEFINITION.value

    # 2. First resume runs _phase_plan() (does NOT skip planning!) and pauses at AFTER_INITIAL_RESEARCH_PLAN
    p = orch.resume()
    assert p.state == ProjectState.PAUSED
    assert p.review_gate_pending == ReviewGate.AFTER_INITIAL_RESEARCH_PLAN.value
    plans = orch.repos.plans.all(p.id)
    assert len(plans) == 1
    assert len(plans[0].branches) >= 1
    assert len(orch.repos.queries.all(p.id)) >= 1

    # 3. Continue resuming through remaining gates (AFTER_FIRST_RESEARCH_CYCLE and/or BEFORE_FINAL_SYNTHESIS)
    seen_gates = [
        ReviewGate.AFTER_PROBLEM_DEFINITION.value,
        ReviewGate.AFTER_INITIAL_RESEARCH_PLAN.value,
    ]
    for _ in range(4):
        if p.state == ProjectState.COMPLETED:
            break
        assert p.state == ProjectState.PAUSED
        if p.review_gate_pending:
            seen_gates.append(p.review_gate_pending)
        p = orch.resume()

    assert p.state == ProjectState.COMPLETED
    assert ReviewGate.BEFORE_FINAL_SYNTHESIS.value in seen_gates
    assert (orch.ws.reports / "info.md").exists()
