import pytest

from research_engine.core.state_machine import StateMachine
from research_engine.models.enums import ProjectState
from research_engine.storage.database import Database
from research_engine.storage.repositories import Repositories
from research_engine.models.project import ResearchProject


@pytest.fixture()
def sm(tmp_path):
    db = Database(tmp_path / "t.sqlite")
    repos = Repositories(db)
    project = ResearchProject(question_raw="q")
    repos.projects.save(project)
    return StateMachine(repos), repos, project


def test_happy_path_transitions(sm):
    state_machine, _, p = sm
    path = [ProjectState.CLARIFYING, ProjectState.PLANNED,
            ProjectState.SEARCHING, ProjectState.FETCHING, ProjectState.EXTRACTING,
            ProjectState.VERIFYING, ProjectState.ANALYZING_GAPS,
            ProjectState.GENERATING_FOLLOWUPS, ProjectState.CONVERGED,
            ProjectState.SYNTHESIZING, ProjectState.COMPLETED]
    for target in path:
        state_machine.transition(p, target, "test")
    assert p.state == ProjectState.COMPLETED


def test_illegal_transition_rejected(sm):
    state_machine, _, p = sm
    with pytest.raises(ValueError):
        state_machine.transition(p, ProjectState.COMPLETED)


def test_transition_persisted(sm):
    state_machine, repos, p = sm
    state_machine.transition(p, ProjectState.CLARIFYING, "test")
    loaded = repos.projects.get(p.id)
    assert loaded.state == ProjectState.CLARIFYING
