"""Explicit project state machine.

The orchestrator is the ONLY component allowed to call transition().
All transitions are validated against ALLOWED and logged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from research_engine.models.enums import ProjectState
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)

ALLOWED: dict[ProjectState, set[ProjectState]] = {
    ProjectState.CREATED: {ProjectState.CLARIFYING, ProjectState.FAILED, ProjectState.CANCELLED},
    ProjectState.CLARIFYING: {ProjectState.PLANNED, ProjectState.PAUSED, ProjectState.FAILED, ProjectState.CANCELLED},
    # CLARIFYING -> PLANNED happens after plan generated; keep name for spec compat
    ProjectState.PLANNED: {ProjectState.SEARCHING, ProjectState.PAUSED, ProjectState.FAILED, ProjectState.CANCELLED},
    ProjectState.SEARCHING: {ProjectState.FETCHING, ProjectState.ANALYZING_GAPS,
                             ProjectState.GENERATING_FOLLOWUPS, ProjectState.CONVERGED,
                             ProjectState.PAUSED, ProjectState.FAILED, ProjectState.CANCELLED},
    ProjectState.FETCHING: {ProjectState.EXTRACTING, ProjectState.SEARCHING,
                            ProjectState.ANALYZING_GAPS, ProjectState.PAUSED,
                            ProjectState.FAILED, ProjectState.CANCELLED},
    ProjectState.EXTRACTING: {ProjectState.VERIFYING, ProjectState.FETCHING,
                              ProjectState.PAUSED, ProjectState.FAILED, ProjectState.CANCELLED},
    ProjectState.VERIFYING: {ProjectState.ANALYZING_GAPS, ProjectState.EXTRACTING,
                             ProjectState.PAUSED, ProjectState.FAILED, ProjectState.CANCELLED},
    ProjectState.ANALYZING_GAPS: {ProjectState.GENERATING_FOLLOWUPS, ProjectState.SYNTHESIZING,
                                  ProjectState.CONVERGED, ProjectState.PAUSED,
                                  ProjectState.FAILED, ProjectState.CANCELLED},
    ProjectState.GENERATING_FOLLOWUPS: {ProjectState.SEARCHING, ProjectState.CONVERGED,
                                        ProjectState.SYNTHESIZING, ProjectState.PAUSED,
                                        ProjectState.FAILED, ProjectState.CANCELLED},
    ProjectState.ITERATING: {ProjectState.SEARCHING, ProjectState.ANALYZING_GAPS,
                             ProjectState.PAUSED, ProjectState.FAILED, ProjectState.CANCELLED},
    ProjectState.CONVERGED: {ProjectState.SYNTHESIZING, ProjectState.PAUSED,
                             ProjectState.FAILED, ProjectState.CANCELLED},
    ProjectState.SYNTHESIZING: {ProjectState.COMPLETED, ProjectState.FAILED, ProjectState.CANCELLED},
    ProjectState.COMPLETED: {ProjectState.SEARCHING, ProjectState.CLARIFYING},  # continuation
    ProjectState.PAUSED: {
        ProjectState.CLARIFYING, ProjectState.PLANNED, ProjectState.SEARCHING,
        ProjectState.FETCHING, ProjectState.EXTRACTING, ProjectState.VERIFYING,
        ProjectState.ANALYZING_GAPS, ProjectState.GENERATING_FOLLOWUPS, ProjectState.ITERATING,
    },
    ProjectState.FAILED: {ProjectState.SEARCHING, ProjectState.SYNTHESIZING},
    ProjectState.CANCELLED: set(),
}


class StateMachine:
    def __init__(self, repos: Repositories):
        self.repos = repos

    def can_transition(self, current: ProjectState, target: ProjectState) -> bool:
        return target in ALLOWED.get(current, set())

    def transition(self, project, target: ProjectState, reason: str = "") -> None:
        current = project.state
        if current == target:
            return
        if not self.can_transition(current, target):
            raise ValueError(f"Illegal state transition {current.value} -> {target.value} ({reason})")
        log.info("state %s -> %s (%s)", current.value, target.value, reason)
        project.state = target
        project.updated_at = datetime.now(timezone.utc)
        self.repos.projects.save(project)
