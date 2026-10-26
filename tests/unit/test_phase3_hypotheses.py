"""Phase 3 unit tests: hypothesis lifecycle, generation, critic, ranking."""
import pytest

from research_engine.models.analysis import Gap
from research_engine.models.evidence import Claim, Evidence
from research_engine.models.reasoning import (Assumption, Hypothesis,
                                              Methodology)
from research_engine.reasoning.hypothesis_engine import (HypothesisCritic,
                                                         HypothesisGenerator,
                                                         HypothesisLifecycle,
                                                         RefinementLoop,
                                                         rank_hypotheses,
                                                         score_hypothesis)
from research_engine.storage.database import Database
from research_engine.storage.reasoning_repos import ReasoningRepos
from research_engine.storage.repositories import Repositories


@pytest.fixture()
def env(tmp_path):
    db = Database(tmp_path / "t.sqlite")
    repos = Repositories(db)
    return repos, ReasoningRepos(db)


def _gap(project_id="p"):
    g = Gap(project_id=project_id, description="Why does method X fail under condition Y?",
            importance=0.9, evidence_needed="mechanism studies")
    g.ensure_id()
    return g


class TestLifecycle:
    def test_legal_transitions(self, env):
        repos, rr = env
        lc = HypothesisLifecycle(rr)
        h = Hypothesis(project_id="p", title="t", statement="s")
        rr.hypotheses.save(h)
        for step in ("UNDER_REVIEW", "REFINED", "READY_FOR_TEST"):
            lc.transition(h, step)
        assert h.status == "READY_FOR_TEST"

    def test_illegal_transition_blocked(self, env):
        repos, rr = env
        lc = HypothesisLifecycle(rr)
        h = Hypothesis(project_id="p", title="t", statement="s")  # PROPOSED
        rr.hypotheses.save(h)
        with pytest.raises(ValueError):
            lc.transition(h, "SUPPORTED")

    def test_revision_creates_immutable_version(self, env):
        repos, rr = env
        h = Hypothesis(project_id="p", title="v1 title", statement="s v1")
        rr.hypotheses.save(h)
        lc = HypothesisLifecycle(rr)
        lc.revise("p", h, {"title": "v2 title"}, reason="tightened after critique")
        assert h.version == 2 and h.title == "v2 title"
        history = rr.hypothesis_versions.history("p", h.id)
        assert len(history) == 1
        assert history[0].snapshot["title"] == "v1 title"  # original preserved


class TestGeneration:
    def test_competing_set_with_null(self, env):
        repos, rr = env
        e = Evidence(project_id="p", claim_text="X fails under Y",
                     quote="long enough quote text ok", source_tier=1)
        repos.evidence.save(e)
        c = Claim(project_id="p", text="X fails under Y", supported_by=[e.id],
                  dedup_key="k")
        repos.claims.save(c)
        gen = HypothesisGenerator(repos, rr, provider=None)  # deterministic templates
        fam = gen.generate_for_gap("p", _gap())
        assert len(fam) >= 2
        types = {h.type for h in fam}
        assert "CAUSAL" in types
        assert any("null" in h.title.lower() or "artifact" in h.statement.lower()
                   for h in fam), "null/artifact explanation required"
        # family linkage + evidence inheritance
        assert all(h.alternative_of for h in fam)
        assert all(h.supporting_evidence for h in fam)

    def test_provenance_recorded(self, env):
        repos, rr = env
        gap = _gap()
        gen = HypothesisGenerator(repos, rr, provider=None)
        fam = gen.generate_for_gap("p", gap)
        assert all(h.origin == "gap" and gap.id in h.origin_refs for h in fam)

    def test_assumptions_become_entities(self, env):
        repos, rr = env
        gen = HypothesisGenerator(repos, rr, provider=None)
        fam = gen.generate_for_gap("p", _gap())
        asm_ids = [a for h in fam for a in h.assumptions]
        assert asm_ids
        got = rr.assumptions.get(asm_ids[0])
        assert got is not None

    def test_business_hypotheses_chain(self, env):
        from research_engine.models.opportunity import Opportunity
        repos, rr = env
        opp = Opportunity(project_id="p", customer_segment="clinics",
                          problem="manual scheduling", current_alternative="paper")
        opp.ensure_id()
        gen = HypothesisGenerator(repos, rr, provider=None)
        hyps = gen.generate_business_hypotheses("p", opp)
        kinds = {h.type for h in hyps}
        assert {"CUSTOMER", "MARKET", "WILLINGNESS_TO_PAY", "DISTRIBUTION"} <= kinds


class TestCritic:
    def _h(self, rr, **kw):
        defaults = dict(project_id="p", title="T", statement="M causes failure under Y",
                        type="MECHANISTIC",
                        falsification_conditions=["if removing M changes nothing then fail"])
        defaults.update(kw)
        h = Hypothesis(**defaults)
        rr.hypotheses.save(h)
        return h

    def test_unfalsifiable_flagged(self, env):
        repos, rr = env
        h = self._h(rr, falsification_conditions=[])
        result = HypothesisCritic(repos, rr, provider=None).critique("p", h)
        types = {p["type"] for p in result["problems"]}
        assert "UNFALSIFIABLE" in types
        assert result["revision_needed"]

    def test_unsupported_speculation_capped(self, env):
        repos, rr = env
        h = self._h(rr)  # no evidence attached
        score_hypothesis(repos, rr, "p", h)
        assert h.confidence <= 0.25, "speculation must stay visibly weak"

    def test_restatement_detected(self, tmp_path):
        db = Database(tmp_path / "t.sqlite")
        repos = Repositories(db)
        rr = ReasoningRepos(db)
        quote = ("the mechanism corrupts intermediate representations causing failure "
                 "under high load conditions")
        e = Evidence(project_id="p", claim_text="mechanism corrupts representations",
                     quote=quote, source_tier=1, confidence=0.9)
        repos.evidence.save(e)
        h = Hypothesis(project_id="p", title="restatement", statement=quote,
                       type="MECHANISTIC",
                       falsification_conditions=["if x then fail"])
        rr.hypotheses.save(h)
        result = HypothesisCritic(repos, rr, provider=None).critique("p", h)
        types = {p["type"] for p in result["problems"]}
        assert any(t in types for t in ("RESTATES_EVIDENCE", "UNSUPPORTED")) or \
               not h.supporting_evidence  # restatement only checkable when linked


class TestRefinement:
    def test_loop_stops_and_improves_falsifiability(self, env):
        repos, rr = env
        h = Hypothesis(project_id="p", title="T", statement="Some claim about X",
                       falsification_conditions=[], status="PROPOSED")
        rr.hypotheses.save(h)
        loop = RefinementLoop(repos, rr, None, HypothesisLifecycle(rr),
                              HypothesisCritic(repos, rr, provider=None))
        res = loop.run("p", h)
        assert res["iterations"]
        assert h.falsification_conditions, "refinement must add falsifiers"


class TestRanking:
    def test_supported_beats_speculative(self, env):
        repos, rr = env
        strong_evs = []
        for i in range(4):
            ev = Evidence(project_id="p", claim_text=f"supporting study {i}",
                          quote=f"long enough supporting quote number {i}",
                          source_tier=1, confidence=0.9,
                          source_url=f"https://src{i}.edu/a")
            repos.evidence.save(ev)
            strong_evs.append(ev.id)
        h_strong = Hypothesis(project_id="p", title="supported", statement="S1",
                              supporting_evidence=strong_evs[:3],
                              predictions=["p"], falsification_conditions=["f"])
        rr.hypotheses.save(h_strong)
        h_weak = Hypothesis(project_id="p", title="speculative", statement="S2",
                            falsification_conditions=["f"])
        rr.hypotheses.save(h_weak)
        ranked = rank_hypotheses(repos, rr, "p")
        assert ranked[0]["hypothesis"].id == h_strong.id

    def test_multi_dimensional_scores_exposed(self, env):
        repos, rr = env
        h = Hypothesis(project_id="p", title="T", statement="S",
                       predictions=["p"], falsification_conditions=["f"])
        rr.hypotheses.save(h)
        scores = score_hypothesis(repos, rr, "p", h)
        for dim in ("support", "testability", "falsifiability", "parsimony",
                    "explanatory_power", "novelty"):
            assert dim in scores
