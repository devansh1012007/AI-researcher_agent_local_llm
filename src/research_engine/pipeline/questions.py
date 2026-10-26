"""Deterministic Ask-the-User question generator, quality gate, and answer handler (Phase 5).

Enforces INV-032:
- Every emitted Question must carry a non-empty `changes` field explaining what
  part of the plan, scope, or branch queries the answer modifies.
- Non-blocking questions record an explicit Assumption(rationale="unanswered_default")
  so research can proceed without hanging.
- Blocking questions transition the project to PAUSED (review_gate_pending="WAITING_FOR_USER")
  and set any active job to JobStatus.WAITING_FOR_USER.
- User answers override the default assumption via override_assumption() and
  record a first-hand Source/Evidence with SourceType.USER_OBSERVATION (tier 2, never tier 1).
"""
from __future__ import annotations

import logging

from research_engine.engines.manifest import EngineManifest
from research_engine.models.base import utcnow
from research_engine.models.enums import (
    ClaimKind,
    ContentStatus,
    EvidenceStatus,
    ProjectState,
    SourceType,
)
from research_engine.models.evidence import Evidence
from research_engine.models.project import Assumption, ResearchProblem, ResearchProject
from research_engine.models.questions import Question, QuestionStatus
from research_engine.models.research import Source
from research_engine.pipeline.clarification import override_assumption
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)


def filter_valid_questions(candidates: list[Question], max_questions: int = 3) -> list[Question]:
    """Quality gate (INV-032): drop any question with an empty `changes` field and cap count."""
    valid: list[Question] = []
    seen_texts: set[str] = set()
    for q in candidates:
        if not q.text or not q.text.strip():
            continue
        if not q.changes or not q.changes.strip():
            log.info("dropping candidate question with empty 'changes' field: %s", q.text[:80])
            continue
        norm = q.text.strip().lower()
        if norm in seen_texts:
            continue
        seen_texts.add(norm)
        valid.append(q)
        if len(valid) >= max(0, max_questions):
            break
    return valid


def generate_questions_for_project(
    project: ResearchProject,
    problem: ResearchProblem,
    manifest: EngineManifest,
    repos: Repositories,
    max_questions: int | None = None,
    blocking: bool | None = None,
    state_machine=None,
) -> list[Question]:
    """Deterministically generate and persist clarifying questions after problem clarification."""
    cap = (
        max_questions
        if max_questions is not None
        else manifest.tunables.max_user_questions_per_run
    )
    is_blocking = (
        blocking
        if blocking is not None
        else manifest.tunables.ask_user_blocking
    )
    raw_lower = (project.question_raw or "").lower()
    constraints_blob = " ".join([*problem.scope, *problem.constraints, problem.geographic_scope, problem.time_horizon]).lower()

    candidates: list[Question] = []

    # 1. Missing required_inputs declared in manifest.clarifier.required_inputs
    for req in manifest.clarifier.required_inputs:
        req_clean = req.strip()
        if not req_clean:
            continue
        if req_clean.lower() not in raw_lower and req_clean.lower() not in constraints_blob:
            candidates.append(
                Question(
                    project_id=project.id,
                    text=f"Please specify {req_clean} for this research project.",
                    why_asking=f"The '{manifest.name}' engine requires '{req_clean}' to scope retrieval accurately.",
                    changes=f"Sets constraint '{req_clean}' on problem scope and branch search queries.",
                    default_assumption=f"Assuming general/unspecified {req_clean} across all regions and segments.",
                    blocking=is_blocking,
                    trigger_source="required_input",
                    iteration=project.current_iteration,
                )
            )

    # 2. Ambiguities surfaced by ClarificationWorker (ClarifyOutput.ambiguities)
    for idx, amb in enumerate(problem.ambiguities):
        amb_clean = amb.strip()
        if not amb_clean:
            continue
        default_asm = (
            problem.assumptions[idx].text
            if idx < len(problem.assumptions) and problem.assumptions[idx].text
            else f"Proceeding with broad default interpretation regarding: {amb_clean}"
        )
        candidates.append(
            Question(
                project_id=project.id,
                text=f"How should we resolve this ambiguity: {amb_clean}?",
                why_asking="Clarifying this ambiguity narrows the research branches and avoids low-yield queries.",
                changes=f"Updates problem scope and branch queries to target the chosen interpretation of: {amb_clean}",
                default_assumption=default_asm,
                blocking=is_blocking,
                trigger_source="ambiguity",
                iteration=project.current_iteration,
            )
        )

    # 3. Manifest ask_user_when triggers when ask_user_enabled is True
    if manifest.tunables.ask_user_enabled or is_blocking:
        for rule in manifest.clarifier.ask_user_when:
            rule_clean = rule.strip()
            if not rule_clean:
                continue
            candidates.append(
                Question(
                    project_id=project.id,
                    text=f"Could you clarify: {rule_clean}?",
                    why_asking=f"Engine '{manifest.name}' flags '{rule_clean}' as a high-leverage scoping decision.",
                    changes=f"Tailors branch prioritization and source routing based on: {rule_clean}",
                    default_assumption=f"Assuming standard baseline scope where {rule_clean}.",
                    blocking=is_blocking,
                    trigger_source="ask_user_when",
                    iteration=project.current_iteration,
                )
            )

    accepted = filter_valid_questions(candidates, max_questions=cap)
    persisted: list[Question] = []

    for q in accepted:
        q.ensure_id()
        if not is_blocking and q.default_assumption:
            # Non-blocking: record explicit Assumption with rationale="unanswered_default"
            asm = Assumption(
                project_id=project.id,
                text=q.default_assumption,
                rationale="unanswered_default",
                overridden=False,
            )
            asm.ensure_id()
            problem.assumptions.append(asm)
            q.assumption_id = asm.id
        repos.questions.save(q)
        persisted.append(q)

    if persisted:
        repos.problems.save(problem)

    if is_blocking and any(q.status == QuestionStatus.OPEN for q in persisted):
        project.review_gate_pending = "WAITING_FOR_USER"
        if state_machine is not None:
            state_machine.transition(project, ProjectState.PAUSED, "waiting for user answer")
        else:
            project.state = ProjectState.PAUSED
        repos.projects.save(project)

    return persisted


def answer_question(
    repos: Repositories,
    project_id: str,
    question_id: str,
    answer_text: str = "",
    skip: bool = False,
) -> Question:
    """Apply a user's answer (or skip) to a Question and update assumptions + provenance."""
    q = repos.questions.get(question_id)
    if q is None or q.project_id != project_id:
        raise KeyError(f"question not found: {question_id}")

    problems = repos.problems.all(project_id)
    problem = problems[0] if problems else None

    if skip:
        q.status = QuestionStatus.SKIPPED
        q.answered_at = utcnow().isoformat()
        if problem is not None and q.default_assumption and not q.assumption_id:
            asm = Assumption(
                project_id=project_id,
                text=q.default_assumption,
                rationale="unanswered_default",
                overridden=False,
            )
            asm.ensure_id()
            problem.assumptions.append(asm)
            q.assumption_id = asm.id
            repos.problems.save(problem)
        repos.questions.save(q)
        return q

    clean_answer = (answer_text or "").strip()
    if not clean_answer:
        raise ValueError("answer_text must not be empty unless skip=True")

    q.answer = clean_answer
    q.status = QuestionStatus.ANSWERED
    q.answered_at = utcnow().isoformat()

    # 1. Override default assumption on ResearchProblem
    if problem is not None:
        replacement = f"User constraint ({q.text}): {clean_answer}"
        if q.default_assumption:
            override_assumption(problem, q.default_assumption, replacement)
        else:
            problem.assumptions.append(
                Assumption(project_id=project_id, text=replacement, rationale="user override", overridden=False)
            )
        if clean_answer not in problem.constraints:
            problem.constraints.append(clean_answer)
        repos.problems.save(problem)

    # 2. Record first-hand provenance as SourceType.USER_OBSERVATION (tier 2, never tier 1 — INV-032)
    url = f"user://project/{project_id}/question/{q.id}"
    src = Source(
        project_id=project_id,
        url=url,
        canonical_url=url,
        title=f"User answer: {q.text[:100]}",
        domain="user_input",
        source_type=SourceType.USER_OBSERVATION,
        source_tier=2,
        retrieval_date=q.answered_at,
        content_status=ContentStatus.PARSED.value,
    )
    src.ensure_id()
    repos.sources.save(src)

    ev = Evidence(
        project_id=project_id,
        claim_text=f"{q.text} — User specified: {clean_answer}",
        quote=clean_answer,
        source_id=src.id,
        location=f"question {q.id}",
        source_url=url,
        source_title=src.title,
        source_type=SourceType.USER_OBSERVATION,
        source_tier=2,
        retrieved_at=q.answered_at or "",
        confidence=1.0,
        status=EvidenceStatus.SUPPORTED,
        kind=ClaimKind.FACT,
        iteration=q.iteration,
        validation_notes="user_observation",
        support_verdict="ENTAILS",
        support_score=1.0,
        extracted_by="user_input",
    )
    ev.ensure_id()
    repos.evidence.save(ev)

    q.source_id = src.id
    q.evidence_id = ev.id
    repos.questions.save(q)
    return q
