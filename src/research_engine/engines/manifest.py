"""Declarative Engine Pack manifest schema (Pydantic models)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from research_engine.engines.skills import SkillDoc, render_skills_guidance


class EngineValidationError(ValueError):
    """Raised when an engine manifest fails static validation."""

    def __init__(self, errors: list[str], warnings: list[str] | None = None):
        self.errors = list(errors)
        self.warnings = list(warnings or [])
        super().__init__("; ".join(self.errors))


class BranchSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    default_question: str = "What is the current evidence regarding: {question}?"
    importance: float = 0.7
    required_evidence: str = "any credible supporting evidence"
    route: list[str] = Field(default_factory=lambda: ["web"])
    fallback: bool = True


class ClarifierSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hint: str = ""
    prompt_template: str = "problem_clarifier"
    required_inputs: list[str] = Field(default_factory=list)
    ask_user_when: list[str] = Field(default_factory=list)


class PlanningSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fallback_to_branches: bool = True
    source_preferences: list[str] = Field(default_factory=lambda: ["web"])
    branches: list[BranchSpec] = Field(default_factory=list)


class ExtractionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_hint: str = ""
    prompt_template: str = "evidence_extractor"
    domain_schema: str | None = None
    require_verbatim_quote: bool = True
    require_claim_support: bool = True


class AnalysisSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structural_checks: list[str] = Field(default_factory=list)
    specialist_pipeline: str | None = None


class LoopStepSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: str
    pause_after: bool = False
    gate: str | None = None
    blocking: bool = False
    max_questions: int = 3
    budget: str | None = None
    max_parallel: str | None = None


class StopConditionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    op: str
    value: float | int
    after_iteration: int = 1


class LoopSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    setup: list[LoopStepSpec] = Field(default_factory=list)
    per_iteration: list[LoopStepSpec] = Field(default_factory=list)
    stop_when: list[StopConditionSpec] = Field(default_factory=list)
    synthesis: list[LoopStepSpec] = Field(default_factory=list)


class ReportEntrySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    file: str


class ReportsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    core: list[str] = Field(
        default_factory=lambda: [
            "problem.md",
            "research_plan.md",
            "info.md",
            "sources.md",
            "gaps.md",
            "research_log.md",
        ]
    )
    domain: list[ReportEntrySpec] = Field(default_factory=list)
    intelligence: list[ReportEntrySpec] = Field(default_factory=list)
    reasoning: list[ReportEntrySpec] = Field(default_factory=list)


class TunablesSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_iterations: int | None = None
    max_queries_per_iteration: int | None = None
    max_documents: int | None = None
    max_sources_total: int | None = None
    max_llm_calls: int | None = None
    max_wall_clock_minutes: int | None = None
    new_evidence_threshold: float | None = None
    duplicate_rate_converged: float | None = None
    results_per_query: int | None = None
    max_chunk_chars: int | None = None
    chunk_overlap_chars: int | None = None
    review_gates_enabled: bool | None = None
    ask_user_enabled: bool = False
    ask_user_blocking: bool = False
    max_user_questions_per_run: int = 3


class SafetySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_skip_quote_verification: bool = False
    allow_skip_claim_support: bool = False
    allow_network_in_local_only: bool = False
    require_counterevidence_for_opportunities: bool = True


class EngineManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    name: str
    display_name: str
    version: str = "1.0.0"
    description: str = ""
    extends: str | None = None

    clarifier: ClarifierSpec = Field(default_factory=ClarifierSpec)
    planning: PlanningSpec = Field(default_factory=PlanningSpec)
    extraction: ExtractionSpec = Field(default_factory=ExtractionSpec)
    analysis: AnalysisSpec = Field(default_factory=AnalysisSpec)
    loop: LoopSpec = Field(default_factory=LoopSpec)
    reports: ReportsSpec = Field(default_factory=ReportsSpec)
    tunables: TunablesSpec = Field(default_factory=TunablesSpec)
    safety: SafetySpec = Field(default_factory=SafetySpec)

    # Runtime metadata populated by loader (ignored in YAML if omitted)
    pack_dir: str = Field(default="", exclude=True)
    source_layer: str = Field(default="builtin", exclude=True)
    skills: list[Any] = Field(default_factory=list, exclude=True)
    domain_schema_dict: dict[str, Any] | None = Field(default=None, exclude=True)

    def branch_categories(self) -> list[str]:
        return [b.category for b in self.planning.branches]

    def fallback_branches(self) -> list[BranchSpec]:
        fb = [b for b in self.planning.branches if b.fallback]
        return fb if fb else list(self.planning.branches)

    def routes_by_category(self) -> dict[str, list[str]]:
        return {b.category: list(b.route) for b in self.planning.branches}

    def report_files(self) -> list[str]:
        """Legacy-compatible report file list (core + domain report files)."""
        out = list(self.reports.core)
        for d in self.reports.domain:
            if d.file not in out:
                out.append(d.file)
        return out

    def guidance_for(self, phase: str | None = None) -> str:
        skill_docs = [s for s in self.skills if isinstance(s, SkillDoc)]
        return render_skills_guidance(skill_docs, phase=phase)

    def prompts_dir(self) -> Path | None:
        if not self.pack_dir:
            return None
        p = Path(self.pack_dir) / "prompts"
        return p if p.is_dir() else None
