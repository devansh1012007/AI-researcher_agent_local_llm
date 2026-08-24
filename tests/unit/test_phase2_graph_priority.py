"""Phase 2 unit tests: graph, priority/coverage, structural gaps."""
import pytest

from research_engine.models.evidence import Claim, Evidence
from research_engine.models.research import ResearchBranch
from research_engine.reasoning.priority import (BranchCoverageModel,
                                                PriorityItem,
                                                evidence_deficit,
                                                rank_priorities)
from research_engine.reasoning.structural_gaps import StructuralGapDetector
from research_engine.storage.database import Database
from research_engine.storage.graph_store import GraphEntity, GraphStore, normalize_name
from research_engine.storage.repositories import Repositories


@pytest.fixture()
def env(tmp_path):
    db = Database(tmp_path / "t.sqlite")
    repos = Repositories(db)
    return repos, GraphStore(db)


class TestGraphStore:
    def test_entity_resolution_same_name(self, env):
        repos, g = env
        a = g.upsert_entity(GraphEntity(project_id="p", type="company", name="OpenAI"))
        b = g.upsert_entity(GraphEntity(project_id="p", type="company", name="OpenAI, Inc."))
        assert a.id == b.id  # normalized to same node

    def test_different_type_not_merged(self, env):
        repos, g = env
        a = g.upsert_entity(GraphEntity(project_id="p", type="company", name="Acme"))
        b = g.upsert_entity(GraphEntity(project_id="p", type="concept", name="Acme"))
        assert a.id != b.id

    def test_relationship_collapse(self, env):
        repos, g = env
        x = g.upsert_entity(GraphEntity(project_id="p", type="concept", name="X"))
        y = g.upsert_entity(GraphEntity(project_id="p", type="concept", name="Y"))
        r1 = g.add_relationship(__import__("research_engine.storage.graph_store",
                                           fromlist=["Relationship"]).Relationship(
            project_id="p", source_id=x.id, target_id=y.id, relationship_type="mentions"))
        r2 = g.add_relationship(__import__("research_engine.storage.graph_store",
                                           fromlist=["Relationship"]).Relationship(
            project_id="p", source_id=y.id, target_id=x.id, relationship_type="mentions"))
        assert r1.id == r2.id
        assert len(g.relationships("p", "mentions")) == 1

    def test_neighbors(self, env):
        repos, g = env
        x = g.upsert_entity(GraphEntity(project_id="p", type="concept", name="X"))
        y = g.upsert_entity(GraphEntity(project_id="p", type="concept", name="Y"))
        from research_engine.storage.graph_store import Relationship
        g.add_relationship(Relationship(project_id="p", source_id=x.id,
                                        target_id=y.id, relationship_type="mentions"))
        nb = g.neighbors("p", x.id)
        assert len(nb) == 1 and nb[0][1].name == "Y"


class TestPriorityModel:
    def test_priority_formula_orders_sensibly(self):
        important = PriorityItem(kind="gap", ref_id="g1", importance=0.95,
                                 uncertainty=0.8, expected_information_gain=0.85,
                                 evidence_deficit=1.0, downstream_dependency=0.9)
        trivial = PriorityItem(kind="gap", ref_id="g2", importance=0.3,
                               uncertainty=0.7, expected_information_gain=0.6)
        assert important.priority > trivial.priority

    def test_explain_is_transparent(self):
        item = PriorityItem(kind="branch", ref_id="b1", importance=0.5)
        text = item.explain()
        for component in ("imp=", "unc=", "gain=", "deficit="):
            assert component in text

    def test_evidence_deficit_decays(self):
        assert evidence_deficit(0) == 1.0
        assert evidence_deficit(20) < evidence_deficit(2)


class TestCoverage:
    def _env_with_evidence(self, tmp_path, tiers=(1,), n=4, domains=("a.com",)):
        db = Database(tmp_path / "t.sqlite")
        repos = Repositories(db)
        b = ResearchBranch(project_id="p", question="What methods exist?", importance=0.9)
        repos.branches.save(b)
        for i in range(n):
            dom = list(domains)[i % len(domains)]
            ev = Evidence(project_id="p", claim_text=f"claim {i}",
                          quote=f"quote number {i} long enough", branch=b.id,
                          source_tier=tiers[i % len(tiers)],
                          source_url=f"https://{dom}/{i}", published_date="2025-01-01")
            repos.evidence.save(ev)
        return repos, b

    def test_uncovered_branch_scores_zero(self, tmp_path):
        db = Database(tmp_path / "t.sqlite")
        repos = Repositories(db)
        b = ResearchBranch(project_id="p", question="q", importance=0.9)
        cov = BranchCoverageModel(repos).compute("p", [b])
        assert cov[b.id]["coverage"] == 0.0 and cov[b.id]["unanswered"]

    def test_strong_multi_domain_evidence_scores_high(self, tmp_path):
        repos, b = self._env_with_evidence(tmp_path, tiers=(1, 2), n=6,
                                           domains=("x.com", "y.org", "z.net"))
        cov = BranchCoverageModel(repos).compute("p", [b])[b.id]
        assert cov["coverage"] >= 0.7 and cov["answered"]

    def test_weak_single_domain_stays_weak(self, tmp_path):
        repos, b = self._env_with_evidence(tmp_path, tiers=(4, 5), n=6,
                                           domains=("forum.example",))
        cov = BranchCoverageModel(repos).compute("p", [b])[b.id]
        assert not cov["answered"]

    def test_rank_priorities_includes_gaps_and_branches(self, tmp_path):
        repos, b = self._env_with_evidence(tmp_path, n=2)
        items = rank_priorities(repos, "p", [b])
        kinds = {i.kind for i in items}
        assert {"branch"} <= kinds


class TestStructuralGaps:
    def _repos(self, tmp_path):
        db = Database(tmp_path / f"t{abs(hash(tmp_path)) % 99999}.sqlite")
        return Repositories(db)

    def test_source_diversity_gap_fires(self, tmp_path):
        repos = self._repos(tmp_path)
        for i in range(8):
            repos.evidence.save(Evidence(
                project_id="p", claim_text=f"positive result improves {i}",
                quote="long enough quote", source_url=f"https://one.com/{i}",
                source_tier=2))
        gaps = StructuralGapDetector(repos).detect("p", mode="academic")
        cats = {g.category.value for g in gaps}
        assert "SOURCE_DIVERSITY_GAP" in cats

    def test_negative_evidence_gap_fires(self, tmp_path):
        repos = self._repos(tmp_path)
        claims = ["method improves results", "approach outperforms baseline",
                  "system succeeds strongly", "effective adoption grows",
                  "promising gains observed", "strong improvements shown"]
        for i, c in enumerate(claims):
            repos.evidence.save(Evidence(
                project_id="p", claim_text=c, quote="long enough quote",
                source_url=f"https://d{i}.com/{i}", source_tier=2))
        gaps = StructuralGapDetector(repos).detect("p", mode="academic")
        cats = {g.category.value for g in gaps}
        assert "NEGATIVE_EVIDENCE_GAP" in cats

    def test_replication_gap_fires(self, tmp_path):
        repos = self._repos(tmp_path)
        e1 = Evidence(project_id="p", claim_text="important finding A",
                      quote="long enough quote", source_url="https://a.com/1",
                      source_id="s1", source_tier=1, confidence=0.9)
        repos.evidence.save(e1)
        repos.claims.save(Claim(project_id="p", text="important finding A",
                                supported_by=[e1.id], dedup_key="finding",
                                confidence=0.8))
        gaps = StructuralGapDetector(repos).detect("p", mode="startup")
        assert any(g.category.value == "INDEPENDENT_REPLICATION_GAP" for g in gaps)

    def test_no_gaps_without_evidence(self, tmp_path):
        repos = self._repos(tmp_path)
        assert StructuralGapDetector(repos).detect("p", mode="academic") == []
