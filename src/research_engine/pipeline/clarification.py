"""Problem clarification worker (LLM-proposed, harness-owned)."""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from research_engine.models.project import Assumption, ResearchProblem
from research_engine.prompts.registry import get_prompt
from research_engine.providers.llm.base import LLMProvider
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)

MODE_HINTS = {
    "academic": "scientific/technical literature research",
    "startup": "startup & market opportunity research",
}


class _AssumptionOut(BaseModel):
    text: str = ""
    rationale: str = ""


class ClarifyOutput(BaseModel):
    objective: str = ""
    research_question: str = ""
    scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    subquestions: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    desired_depth: str = "survey"
    time_horizon: str = ""
    geographic_scope: str = ""
    evaluation_criteria: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    assumptions: list[_AssumptionOut] = Field(default_factory=list)


class ClarificationWorker:
    def __init__(self, provider: LLMProvider, repos: Repositories):
        self.provider = provider
        self.repos = repos

    def run(self, project_id: str, raw_question: str, mode: str) -> ResearchProblem:
        spec = get_prompt("problem_clarifier")
        user = spec.render(raw_question=raw_question, mode=mode, mode_hint=MODE_HINTS.get(mode, mode))
        out, errors = self.provider.structured(spec.system, user, ClarifyOutput)
        if out is None:
            # deterministic fallback: never block the pipeline on the LLM
            log.warning("clarification failed; using raw question (%s)", errors[-1:])
            out = ClarifyOutput(objective=raw_question, research_question=raw_question,
                                assumptions=[_AssumptionOut(
                                    text="Clarification model unavailable; proceeding with raw request as-is.",
                                    rationale="fallback")])
        problem = ResearchProblem(
            project_id=project_id,
            objective=out.objective or raw_question,
            research_question=out.research_question or raw_question,
            scope=out.scope, out_of_scope=out.out_of_scope,
            subquestions=out.subquestions, entities=out.entities,
            constraints=out.constraints, desired_depth=out.desired_depth or "survey",
            time_horizon=out.time_horizon, geographic_scope=out.geographic_scope,
            evaluation_criteria=out.evaluation_criteria, ambiguities=out.ambiguities,
            assumptions=[Assumption(project_id=project_id, text=a.text, rationale=a.rationale)
                         for a in out.assumptions if a.text],
        )
        problem.ensure_id()
        self.repos.problems.save(problem)
        return problem


def override_assumption(problem: ResearchProblem, assumption_text: str, replacement: str) -> None:
    """User can override any recorded assumption; override is preserved in history."""
    for a in problem.assumptions:
        if a.text == assumption_text:
            a.overridden = True
    from research_engine.models.base import utcnow
    problem.assumptions.append(Assumption(text=replacement, rationale="user override",
                                          overridden=False))
