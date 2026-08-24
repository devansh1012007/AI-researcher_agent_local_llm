"""Repositories for Phase 3 reasoning entities (hypotheses, experiments, ...)."""
from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from research_engine.models.reasoning import (Assumption, Experiment,
                                              ExperimentResult, Hypothesis,
                                              HypothesisVersion, Methodology,
                                              ResearchQuestion)
from research_engine.storage.database import Database

M = TypeVar("M", bound=BaseModel)


def _strip(entity: BaseModel) -> dict:
    import json
    return json.loads(entity.model_dump_json())


def _enum_val(v):
    return getattr(v, "value", v)


class _GenericRepo:
    table = ""
    model: type[BaseModel] = BaseModel

    def __init__(self, db: Database):
        self.db = db

    def save(self, e) -> None:
        if hasattr(e, "ensure_id"):
            e.ensure_id()
        cols = self._index_cols(e)
        payload = _strip(e)
        self.db.upsert(self.table, e.id, getattr(e, "project_id", "") or "global",
                       payload, cols)

    def _index_cols(self, e) -> dict:
        return {}

    def get(self, entity_id: str):
        d = self.db.get(self.table, entity_id)
        return self.model.model_validate(d) if d else None

    def all(self, project_id: str, where: str = "", params: tuple = ()) -> list:
        return [self.model.model_validate(d)
                for d in self.db.list(self.table, project_id, where, params)]

    def count(self, project_id: str, where: str = "", params: tuple = ()) -> int:
        return self.db.count(self.table, project_id, where, params)


class HypothesisRepo(_GenericRepo):
    table = "hypotheses"
    model = Hypothesis

    def _index_cols(self, h: Hypothesis):
        return {"status": h.status, "domain": h.domain, "version": h.version,
                "alternative_of": h.alternative_of}

    def by_status(self, project_id: str, *statuses: str) -> list[Hypothesis]:
        if not statuses:
            return self.all(project_id)
        placeholders = ",".join("?" * len(statuses))
        return self.all(project_id, f"status IN ({placeholders})", tuple(statuses))


class HypothesisVersionRepo(_GenericRepo):
    table = "hypothesis_versions"
    model = HypothesisVersion

    def _index_cols(self, v: HypothesisVersion):
        return {"hypothesis_id": v.hypothesis_id, "version": v.version}

    def history(self, project_id: str, hypothesis_id: str) -> list[HypothesisVersion]:
        rows = self.all(project_id, "hypothesis_id=?", (hypothesis_id,))
        return sorted(rows, key=lambda r: r.version)


class AssumptionRepo(_GenericRepo):
    table = "assumptions2"
    model = Assumption

    def _index_cols(self, a: Assumption):
        return {"kind": a.kind, "status": a.status, "opportunity_id": a.opportunity_id}

    def for_hypothesis(self, project_id: str, hypothesis_id: str) -> list[Assumption]:
        return [a for a in self.all(project_id) if a.hypothesis_id == hypothesis_id]


class ResearchQuestionRepo(_GenericRepo):
    table = "research_questions"
    model = ResearchQuestion

    def _index_cols(self, q: ResearchQuestion):
        return {"gap_ref": q.gap_ref}


class MethodologyRepo(_GenericRepo):
    table = "methodologies"
    model = Methodology

    def _index_cols(self, m: Methodology):
        return {"hypothesis_id": m.hypothesis_id, "tier": m.tier}

    def for_hypothesis(self, project_id: str, hypothesis_id: str) -> list[Methodology]:
        return self.all(project_id, "hypothesis_id=?", (hypothesis_id,))


class ExperimentRepo(_GenericRepo):
    table = "experiments"
    model = Experiment

    def _index_cols(self, x: Experiment):
        return {"hypothesis_id": x.hypothesis_id, "status": x.status,
                "risk_level": x.risk_level}

    def awaiting_approval(self, project_id: str) -> list[Experiment]:
        return self.all(project_id, "status='READY_FOR_HUMAN_APPROVAL'")


class ExperimentResultRepo(_GenericRepo):
    table = "experiment_results"
    model = ExperimentResult

    def _index_cols(self, r: ExperimentResult):
        return {"experiment_id": r.experiment_id}

    def for_experiment(self, project_id: str, experiment_id: str) -> list[ExperimentResult]:
        return self.all(project_id, "experiment_id=?", (experiment_id,))


class ReasoningRepos:
    """Bundle of Phase 3 repositories bound to one Database."""

    def __init__(self, db: Database):
        self.hypotheses = HypothesisRepo(db)
        self.hypothesis_versions = HypothesisVersionRepo(db)
        self.assumptions = AssumptionRepo(db)
        self.research_questions = ResearchQuestionRepo(db)
        self.methodologies = MethodologyRepo(db)
        self.experiments = ExperimentRepo(db)
        self.experiment_results = ExperimentResultRepo(db)
