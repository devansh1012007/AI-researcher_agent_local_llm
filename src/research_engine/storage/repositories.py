"""Typed repositories over the generic JSON-document store."""
from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from research_engine.core.ids import stable_hash
from research_engine.models.analysis import Contradiction, Gap
from research_engine.models.document import Document, DocumentChunk
from research_engine.models.evidence import Claim, Evidence
from research_engine.models.opportunity import Opportunity
from research_engine.models.project import ResearchMetrics, ResearchProblem, ResearchProject, ResearchReport
from research_engine.models.research import ResearchBranch, ResearchPlan, SearchQuery, SearchResult, Source
from research_engine.models.task import Task
from research_engine.storage.database import Database

M = TypeVar("M", bound=BaseModel)


class Repository:
    table = ""
    model: type[BaseModel] = BaseModel

    def __init__(self, db: Database):
        self.db = db

    def save(self, entity) -> None:
        if hasattr(entity, "ensure_id"):
            entity.ensure_id()
        self.db.upsert(self.table, entity.id,
                       getattr(entity, "project_id", "") or "global",
                       _strip(entity), self._index_cols(entity))

    def _index_cols(self, entity) -> dict[str, object]:
        return {}

    def get(self, entity_id: str) -> M | None:
        data = self.db.get(self.table, entity_id)
        return self.model.model_validate(data) if data else None

    def all(self, project_id: str, where: str = "", params: tuple = ()) -> list:
        return [self.model.model_validate(d)
                for d in self.db.list(self.table, project_id, where, params)]

    def count(self, project_id: str, where: str = "", params: tuple = ()) -> int:
        return self.db.count(self.table, project_id, where, params)


def _strip(entity: BaseModel) -> dict:
    return json_loads(entity.model_dump_json())


def _enum_val(v) -> object:
    return getattr(v, "value", v)


def json_loads(s: str) -> dict:
    import json
    return json.loads(s)


class ProjectRepo(Repository):
    table = "projects"
    model = ResearchProject


class ProblemRepo(Repository):
    table = "problems"
    model = ResearchProblem


class PlanRepo(Repository):
    table = "plans"
    model = ResearchPlan


class BranchRepo(Repository):
    table = "branches"
    model = ResearchBranch


class TaskRepo(Repository):
    table = "tasks"
    model = Task

    def _index_cols(self, t: Task):
        return {"type": _enum_val(t.type), "status": _enum_val(t.status),
                "iteration": t.iteration, "priority": t.priority}

    def pending(self, project_id: str) -> list[Task]:
        return self.all(project_id, "status=?", ("PENDING",))


class QueryRepo(Repository):
    table = "queries"
    model = SearchQuery

    def _index_cols(self, q: SearchQuery):
        return {"executed": 1 if q.executed else 0}


class SearchResultRepo(Repository):
    table = "search_results"
    model = SearchResult

    def _index_cols(self, r: SearchResult):
        return {"url": r.url}


class SourceRepo(Repository):
    table = "sources"
    model = Source

    def _index_cols(self, s: Source):
        return {"canonical_url": s.canonical_url, "content_hash": s.content_hash,
                "domain": s.domain, "source_tier": s.source_tier, "status": s.content_status}

    def find_by_canonical_url(self, project_id: str, url: str) -> Source | None:
        rows = self.all(project_id, "canonical_url=?", (url,))
        return rows[0] if rows else None

    def find_by_hash(self, project_id: str, h: str) -> Source | None:
        rows = self.all(project_id, "content_hash=?", (h,))
        return rows[0] if rows else None


class DocumentRepo(Repository):
    table = "documents"
    model = Document

    def _index_cols(self, d: Document):
        return {"source_id": d.source_id, "content_hash": d.content_hash,
                "status": _enum_val(d.content_status)}


class ChunkRepo(Repository):
    table = "chunks"
    model = DocumentChunk

    def _index_cols(self, c: DocumentChunk):
        return {"document_id": c.document_id, "sequence": c.sequence}

    def for_document(self, project_id: str, document_id: str) -> list[DocumentChunk]:
        return sorted(self.all(project_id, "document_id=?", (document_id,)), key=lambda c: c.sequence)


class ClaimRepo(Repository):
    table = "claims"
    model = Claim

    def _index_cols(self, c: Claim):
        return {"dedup_key": c.dedup_key, "branch": c.branch, "kind": _enum_val(c.kind),
                "iteration": c.iteration}

    def find_by_dedup_key(self, project_id: str, key: str) -> Claim | None:
        rows = self.all(project_id, "dedup_key=?", (key,))
        return rows[0] if rows else None


class EvidenceRepo(Repository):
    table = "evidence"
    model = Evidence

    def _index_cols(self, e: Evidence):
        return {
            "claim_text_lower": e.claim_text.lower(),
            "source_id": e.source_id,
            "document_id": e.document_id,
            "status": _enum_val(e.status),
            "tier": e.source_tier,
            "iteration": e.iteration,
            "quote_hash": stable_hash(e.quote),
        }

    def save(self, entity: Evidence) -> None:
        super().save(entity)
        self.db.fts_index(entity.id, entity.project_id, "evidence",
                          f"{entity.claim_text} {entity.quote}")

    def find_by_quote_hash(self, project_id: str, quote: str) -> Evidence | None:
        h = stable_hash(quote)
        rows = self.all(project_id, "quote_hash=?", (h,))
        return rows[0] if rows else None

    def rejected_ratio(self, project_id: str) -> float:
        """P0-04: this is the REJECTION rate (verification failures),
        never to be reported as duplication."""
        total = self.count(project_id)
        rej = self.count(project_id, "status='REJECTED'")
        return rej / total if total else 0.0

    def duplicate_ratio(self, project_id: str) -> float:
        """True duplicate pressure: accepted evidences whose quote-hash was
        already seen earlier in the corpus, over all accepted."""
        rows = self.all(project_id, "status!='REJECTED'")
        if not rows:
            return 0.0
        seen, dups = set(), 0
        for e in sorted(rows, key=lambda x: x.iteration):
            h = getattr(e, "quote_hash", "") or stable_hash(e.quote or "")
            if h in seen:
                dups += 1
            else:
                seen.add(h)
        return dups / len(rows)


class GapRepo(Repository):
    table = "gaps"
    model = Gap

    def _index_cols(self, g: Gap):
        return {"resolved": 1 if g.resolved else 0, "importance": g.importance,
                "category": _enum_val(g.category)}


class ContradictionRepo(Repository):
    table = "contradictions"
    model = Contradiction

    def _index_cols(self, c: Contradiction):
        return {"resolved": 1 if c.resolved else 0}


class MetricsRepo(Repository):
    table = "metrics"
    model = ResearchMetrics

    def _index_cols(self, m: ResearchMetrics):
        return {"iteration": m.iteration}


class ReportRepo(Repository):
    table = "reports"
    model = ResearchReport

    def _index_cols(self, r: ResearchReport):
        return {"kind": r.kind, "path": r.path}


class OpportunityRepo(Repository):
    table = "opportunities"
    model = Opportunity


class Repositories:
    """Bundle of all repos bound to one Database."""

    def __init__(self, db: Database):
        self.db = db
        self.projects = ProjectRepo(db)
        self.problems = ProblemRepo(db)
        self.plans = PlanRepo(db)
        self.branches = BranchRepo(db)
        self.tasks = TaskRepo(db)
        self.queries = QueryRepo(db)
        self.search_results = SearchResultRepo(db)
        self.sources = SourceRepo(db)
        self.documents = DocumentRepo(db)
        self.chunks = ChunkRepo(db)
        self.claims = ClaimRepo(db)
        self.evidence = EvidenceRepo(db)
        self.gaps = GapRepo(db)
        self.contradictions = ContradictionRepo(db)
        self.metrics = MetricsRepo(db)
        self.reports = ReportRepo(db)
        self.opportunities = OpportunityRepo(db)
