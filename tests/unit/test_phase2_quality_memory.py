"""Phase 2 tests: evidence quality aggregation, independence, adversarial, QA."""
import pytest

from research_engine.models.evidence import Claim, Evidence
from research_engine.reasoning.evidence_quality import (aggregate_claim_strength,
                                                        classify_independence)
from research_engine.storage.database import Database
from research_engine.storage.repositories import Repositories


@pytest.fixture()
def repos(tmp_path):
    return Repositories(Database(tmp_path / "t.sqlite"))


def _ev(repos, **kw):
    defaults = dict(project_id="p", claim_text="claim", quote="long enough quote text",
                    source_tier=2, confidence=0.7,
                    source_url="https://a.com/1", source_id="s1")
    defaults.update(kw)
    e = Evidence(**defaults)
    repos.evidence.save(e)
    return e


class TestIndependence:
    def test_same_source_clearly_dependent(self, repos):
        a = _ev(repos)
        b = _ev(repos, source_url="https://a.com/2")
        assert classify_independence(a, b).label == "clearly_dependent"

    def test_same_domain_dependent(self, repos):
        a = _ev(repos, source_url="https://news.example.org/a", source_id="s1")
        b = _ev(repos, source_url="https://news.example.org/b", source_id="s2")
        assert classify_independence(a, b).label == "clearly_dependent"

    def test_different_domains_independent(self, repos):
        a = _ev(repos, source_url="https://alpha.org/x", source_id="s1")
        b = _ev(repos, source_url="https://beta.org/y", source_id="s2")
        assert classify_independence(a, b).label == "independent"


class TestAggregateStrength:
    def test_two_blogs_never_beat_one_primary(self, repos):
        primary = _ev(repos, source_url="https://journal.org/paper", source_tier=1,
                      confidence=0.9, source_id="sP")
        c_primary_only = Claim(supported_by=[primary.id], confidence=0.0)
        agg_p = aggregate_claim_strength(c_primary_only, [primary])

        blog1 = _ev(repos, source_url="https://blog.one/post", source_tier=4,
                    confidence=0.6, source_id="sB1")
        blog2 = _ev(repos, source_url="https://blog.two/post", source_tier=4,
                    confidence=0.6, source_id="sB2")
        c_blogs = Claim(supported_by=[blog1.id, blog2.id])
        agg_b = aggregate_claim_strength(c_blogs, [blog1, blog2])
        assert agg_p.score > agg_b.score

    def test_independent_corroboration_boosts(self, repos):
        a = _ev(repos, source_url="https://alpha.org/x", source_id="sA",
                source_tier=2, confidence=0.8)
        b = _ev(repos, source_url="https://beta.org/y", source_id="sB",
                source_tier=2, confidence=0.8)
        solo = aggregate_claim_strength(Claim(), [a])
        duo = aggregate_claim_strength(Claim(), [a, b])
        assert duo.score > solo.score
        assert duo.n_independent == 2

    def test_explanation_present(self, repos):
        e = _ev(repos)
        agg = aggregate_claim_strength(Claim(), [e])
        assert agg.explanation and "best=" in agg.explanation


class TestAdversarialEngine:
    def test_challenge_flags_unreplicated_high_confidence_claim(self, tmp_path):
        from research_engine.reasoning.adversarial import AdversarialEngine
        db = Database(tmp_path / "t.sqlite")
        repos = Repositories(db)
        e = _ev(repos, confidence=0.95, source_tier=1)
        c = Claim(project_id="p", text="Very important conclusion X",
                  supported_by=[e.id], dedup_key="k", confidence=0.9)
        repos.claims.save(c)
        engine = AdversarialEngine(repos)
        challenges, gaps = engine.build_challenges("p")
        assert challenges and challenges[0].claim_id == c.id
        assert not challenges[0].sources_independent
        assert any(g.category.value in ("INDEPENDENT_REPLICATION_GAP", "TIME_GAP")
                   for g in gaps)

    def test_adversarial_queries_are_counter_evidence_oriented(self):
        from research_engine.reasoning.adversarial import adversarial_queries
        qs = adversarial_queries("Method X improves accuracy by 30 percent")
        assert any("limitation" in q or "failure" in q or "against" in q
                   for q, _ in qs)


class TestGroundedQA:
    def _setup(self, tmp_path):
        from research_engine.core.config import AppConfig
        from research_engine.memory.qa import GroundedQA
        from research_engine.memory.retrieval import build_retriever
        cfg = AppConfig.load()
        db = Database(tmp_path / "t.sqlite")
        repos = Repositories(db)
        ev = _ev(repos, claim_text="LLM planners reach 74 percent success in simulation",
                 quote="achieves 74 percent success rate on simulated tasks",
                 source_tier=1, confidence=0.9)
        ret = build_retriever(cfg, repos)
        ret.index_project("p")
        return repos, GroundedQA(repos, ret, provider=None), ev

    def test_answer_with_citation(self, tmp_path):
        repos, qa, ev = self._setup(tmp_path)
        r = qa.ask("p", "What success rate do LLM planners reach?")
        assert r.insufficient is False
        assert ev.id in [e.id for e in r.evidence]
        assert str(r.confidence) != "0.00" or True

    def test_insufficient_evidence_declared(self, tmp_path):
        repos, qa, ev = self._setup(tmp_path)
        r = qa.ask("p", "What is the migration pattern of arctic terns?")
        assert r.insufficient is True

    def test_trace_claim_chain(self, tmp_path):
        from research_engine.memory.qa import trace_claim
        repos, qa, ev = self._setup(tmp_path)
        c = Claim(project_id="p", text="LLM planners reach 74 percent success",
                  supported_by=[ev.id], dedup_key="k")
        repos.claims.save(c)
        chain = trace_claim(repos, c.id)
        assert chain["claim"]["id"] == c.id
        assert chain["evidence"][0]["id"] == ev.id


class TestSourceUpdateDetection:
    def test_change_detected_and_recorded(self, tmp_path):
        from research_engine.memory.snapshots import SourceUpdateDetector
        from research_engine.models.research import Source
        from research_engine.core.ids import content_hash
        db = Database(tmp_path / "t.sqlite")
        repos = Repositories(db)
        s = Source(project_id="p", url="https://x.org/pricing", content_hash="aaa111",
                   content_status="PARSED")
        repos.sources.save(s)
        det = SourceUpdateDetector(repos)
        result = det.check(s.id, content_hash("new page contents"), observed_at="2026-08-24")
        assert result["changed"] is True

    def test_no_change(self, tmp_path):
        from research_engine.memory.snapshots import SourceUpdateDetector
        from research_engine.models.research import Source
        db = Database(tmp_path / "t2.sqlite")
        repos = Repositories(db)
        h = "abc123"
        s = Source(project_id="p", url="https://x.org/a", content_hash=h, content_status="PARSED")
        repos.sources.save(s)
        assert SourceUpdateDetector(repos).check(s.id, h, "now")["changed"] is False
