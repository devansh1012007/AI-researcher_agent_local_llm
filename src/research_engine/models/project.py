"""Project-level models: ResearchProject, question/problem, assumptions, metrics, report."""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from research_engine.models.base import Entity
from research_engine.models.enums import ClaimKind, ProjectState, StopReason


class ResearchQuestion(Entity):
    PREFIX: ClassVar[str] = "rq"

    text: str = ""
    subquestions: list[str] = Field(default_factory=list)
    branch: str = ""

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)


class Assumption(Entity):
    PREFIX: ClassVar[str] = "asm"

    text: str = ""
    rationale: str = ""
    overridden: bool = False

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)


class ResearchProblem(Entity):
    PREFIX: ClassVar[str] = "prb"

    objective: str = ""
    research_question: str = ""
    scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    subquestions: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    desired_depth: str = ""       # survey | deep-dive | quick-scan
    time_horizon: str = ""
    geographic_scope: str = ""
    evaluation_criteria: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)


class BudgetUsage(BaseModel):
    queries_used: int = 0
    documents_used: int = 0
    llm_calls_used: int = 0
    bytes_downloaded: int = 0
    iterations_used: int = 0


class ResearchMetrics(Entity):
    PREFIX: ClassVar[str] = "met"

    iteration: int = 0
    sources_discovered: int = 0
    sources_accepted: int = 0
    sources_rejected: int = 0
    documents_fetched: int = 0
    documents_failed: int = 0
    evidence_created: int = 0
    evidence_rejected: int = 0
    unique_claims: int = 0
    duplicate_claims: int = 0
    contradictions: int = 0
    gaps_open: int = 0
    gaps_resolved: int = 0
    new_evidence_this_iter: int = 0
    new_claims_this_iter: int = 0
    duplicate_rate: float = 0.0
    new_evidence_rate: float = 0.0
    gap_resolution_rate: float = 0.0
    source_diversity_domains: int = 0
    tier_distribution: dict[str, int] = Field(default_factory=dict)
    llm_calls: int = 0
    errors: int = 0
    retries: int = 0
    duration_seconds: float = 0.0

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)


class ResearchReport(Entity):
    PREFIX: ClassVar[str] = "rep"

    kind: str = "info"          # problem|research_plan|info|sources|gaps|research_log|literature_review|startup_research
    path: str = ""
    generated_at: str = ""
    stop_reason: StopReason | None = None
    budget_limited: bool = False

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)


class ResearchProject(Entity):
    PREFIX: ClassVar[str] = "proj"

    question_raw: str = ""
    mode: str = "academic"
    state: ProjectState = ProjectState.CREATED
    stop_reason: StopReason | None = None
    review_gate_pending: str | None = None     # gate awaiting approval
    current_iteration: int = 0
    budget: BudgetUsage = Field(default_factory=BudgetUsage)
    engine_version: str = "0.1.0"
    schema_version: str = "1"
    config_snapshot: dict = Field(default_factory=dict)

    def ensure_id(self) -> None:
        super().ensure_id(self.PREFIX)
