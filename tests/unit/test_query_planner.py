from research_engine.models.enums import BranchCategory
from research_engine.models.research import ResearchBranch, SearchQuery
from research_engine.pipeline.planning import (QueryPlannerWorker,
                                               queries_similar,
                                               score_information_gain,
                                               select_queries)


def test_similar_queries_detected():
    assert queries_similar("LLM robotic manipulation planning methods",
                           "llm robotic manipulation planning techniques")
    assert not queries_similar("transformer architecture pretraining",
                               "indian restaurant market pricing")


def test_information_gain_ranking():
    important = SearchQuery(text="q1", kind="primary", priority=0.9)
    minor = SearchQuery(text="q2", kind="synonym", priority=0.2)
    b_imp = ResearchBranch(importance=0.9)
    b_min = ResearchBranch(importance=0.2)
    g_imp = score_information_gain(important, b_imp, 0)
    g_min = score_information_gain(minor, b_min, 40)
    assert g_imp > g_min


def test_select_queries_orders_by_gain_and_filters_executed():
    q1 = SearchQuery(text="a", expected_information_gain=0.3, executed=True)
    q2 = SearchQuery(text="b", expected_information_gain=0.9, executed=False)
    q3 = SearchQuery(text="c", expected_information_gain=0.5, executed=False)
    picked = select_queries([q1, q2, q3], budget=2)
    assert [q.text for q in picked] == ["b", "c"]


def _repos(tmp_path):
    from research_engine.storage.database import Database
    from research_engine.storage.repositories import Repositories
    return Repositories(Database(tmp_path / "t.sqlite"))


class _ScriptedProvider:
    """Minimal provider stub for the query planner."""

    def __init__(self, responses):
        self.responses = list(responses)

    def structured(self, system, user, schema, max_attempts=3):
        if not self.responses:
            return None, ["exhausted"]
        raw = self.responses.pop(0)
        try:
            return schema.model_validate(raw), []
        except Exception:
            return None, ["bad"]


def test_query_planner_dedupes_semantically_across_branches(tmp_path):
    repos = _repos(tmp_path)
    b1 = ResearchBranch(project_id="p", question="How do LLMs plan manipulation?",
                        importance=0.9)
    b2 = ResearchBranch(project_id="p", question="What benchmarks evaluate manipulation planning?",
                        importance=0.8)
    repos.branches.save(b1)
    repos.branches.save(b2)
    plan = type("P", (), {"branches": [b1, b2], "objective": "o"})()
    provider = _ScriptedProvider([
        {"queries": [{"text": "LLM manipulation planning methods", "kind": "primary",
                      "reason": "r"}]},
        {"queries": [{"text": "llm manipulation planning methods!", "kind": "synonym",
                      "reason": "near-duplicate should be dropped"},
                     {"text": "manipulation planning benchmark failure cases",
                      "kind": "contradiction", "reason": "adversarial"}]},
    ])
    worker = QueryPlannerWorker(provider, repos)
    created = worker.run("p", plan, iteration=1)
    texts = [q.text for q in created]
    assert len(created) == 2  # near-duplicate removed
    assert any("benchmark" in t for t in texts)
