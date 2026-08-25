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

    def _physical_cols(self) -> set[str]:
        cached = getattr(self, "_phys_cols", None)
        if cached is None:
            rows = self.db.execute(
                f"PRAGMA table_info({self.table})")
            cached = {r["name"] for r in rows}
            self._phys_cols = cached
        return cached

    def find_by_natural_key(self, project_id: str, key_cols: dict) -> object | None:
        """Resolve an entity by its natural-key columns (must be indexed).
        Text keys compare case-insensitively (identity is not casing).
        Physical columns are queried directly; other keys resolve through
        the JSON document."""
        if not key_cols:
            return None
        phys = self._physical_cols()
        conds = []
        params: list = []
        for col, val in key_cols.items():
            if col in phys:
                conds.append(f"{col} LIKE ? COLLATE NOCASE")
                params.append(val)
            else:
                conds.append(f"json_extract(data,'$.{col}') LIKE ? COLLATE NOCASE")
                params.append(val)
        rows = self.db.list(self.table, project_id,
                            " AND ".join(conds), tuple(params))
        return self.model.model_validate(rows[0]) if rows else None

    def save_natural(self, entity, merge: bool = True):
        """INVARIANT-003: idempotent persist by natural key.

        Resolves an existing row via `natural_key(entity)`; merges the
        incoming snapshot into it (list provenance unions) and keeps the
        ORIGINAL identity. Only genuinely new entities mint ids.
        """
        key = self.natural_key(entity) if hasattr(self, "natural_key") else {}
        if not key:
            self.save(entity)
            return entity
        existing = self.find_by_natural_key(entity.project_id, key)
        if existing is not None:
            if merge:
                from research_engine.specialists.startup.identity import merge_entities
                merged = merge_entities(existing, entity)
                merged.updated_at = entity.updated_at
                self.save(merged)
                return merged
            entity.id = existing.id
            self.save(entity)
            return entity
        entity.ensure_id()
        try:
            self.save(entity)
            return entity
        except Exception:
            # lost a race against a unique index: re-resolve and merge
            existing = self.find_by_natural_key(entity.project_id, key)
            if existing is None:
                raise
            if merge:
                from research_engine.specialists.startup.identity import merge_entities
                merged = merge_entities(existing, entity)
                self.save(merged)
                return merged
            entity.id = existing.id
            self.save(entity)
            return entity


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
