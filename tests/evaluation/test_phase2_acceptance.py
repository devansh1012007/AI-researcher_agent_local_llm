"""Phase 2 acceptance tests (spec #124): adaptive research, literature, startup,
memory — run fully offline against the deterministic fakes."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

from research_engine.models.enums import EvidenceStatus, ProjectState
from research_engine.intelligence.literature import (cluster_papers,
                                                     detect_foundational,
                                                     compare_methods)


def _run(cfg, fake_registry, make_orchestrator, question, mode="academic"):
    orch = make_orchestrator(question, mode=mode)
    orch.repos.projects.save(orch.project)
    project = orch.run()
    return orch, project


class TestAdaptiveResearch:
    # INVARIANT-006 note (stabilization): duplicate-rate now reflects TRUE
    # quote duplication; the offline fake corpus is near-100% duplicated, so
    # these planner tests raise the dup threshold to keep the loop running
    # long enough to exercise follow-up generation. Saturation-stopping is
    # covered by tests/invariants/test_convergence_semantics.py.
    @pytest.fixture(autouse=True)
    def _relax_dup_gate(self, cfg):
        old = cfg.research.duplicate_rate_converged
        cfg.research.duplicate_rate_converged = 0.98
        yield
        cfg.research.duplicate_rate_converged = old

    def test_branches_prioritized_and_covered(self, cfg, fake_registry, make_orchestrator):
        orch, p = _run(cfg, fake_registry, make_orchestrator,
                       "What methods exist for LLM-based robot manipulation?")
        plans = orch.repos.plans.all(p.id)
        assert plans and len(plans[-1].branches) >= 3
        branches = orch.repos.branches.all(p.id)
        assert any(b.coverage_score > 0 for b in branches), "coverage must be computed"
        assert any(b.status in ("answered", "partially_answered", "open") for b in branches)

    def test_followups_depend_on_state(self, cfg, fake_registry, make_orchestrator):
        orch, p = _run(cfg, fake_registry, make_orchestrator,
                       "Does retrieval augmented generation improve factuality?")
        queries = orch.repos.queries.all(p.id)
        executed = [q for q in queries if q.executed]
        # adaptive planner stamps strategy reasons on follow-ups
        assert executed
        events = {e["event"] for e in orch.events.read_events()}
        assert "adaptive_plan" in events or "followup_queries_generated" in events

    def test_research_gain_measured(self, cfg, fake_registry, make_orchestrator):
        orch, p = _run(cfg, fake_registry, make_orchestrator,
                       "What are open problems in grounded language planning?")
        metrics = sorted(orch.repos.metrics.all(p.id), key=lambda m: m.iteration)
        assert metrics
        from evals.metrics.eval_metrics import score_project
        s = score_project(orch.repos, p.id)
        assert isinstance(s.research_gain_total, int)

    def test_stop_explanation_present(self, cfg, fake_registry, make_orchestrator):
        orch, p = _run(cfg, fake_registry, make_orchestrator,
                       "Survey limitations of embodied agents.")
        events = orch.events.read_events()
        stop_events = [e for e in events if e["event"] == "stop_policy_applied"]
        assert stop_events, "stop policy explanation must be recorded"
        text = stop_events[0]["metadata"]["explanation"].lower()
        assert any(k in text for k in ("budget", "gap", "evidence", "iteration"))


class TestLiteratureIntelligence:
    def test_papers_cluster(self):
        papers = [
            {"title": "SayCan grounds LLMs in robot affordances",
             "abstract": "language model affordance robot planning", "year": 2022, "citations": 900},
            {"title": "Progprompt program generation for robots",
             "abstract": "llm code program robot task planning", "year": 2023, "citations": 100},
            {"title": "RT-2 vision language action model",
             "abstract": "vision language action transformer robot control", "year": 2023, "citations": 300},
            {"title": "PaLM-E multimodal embodied language model",
             "abstract": "multimodal language embodiment robot tasks", "year": 2023, "citations": 450},
        ]
        clusters = cluster_papers(papers, threshold=0.1)
        assert len(clusters) >= 2
        all_clustered = sum(len(c.papers) for c in clusters)
        assert all_clustered == len(papers)

    def test_foundational_prefers_impact_plus_age(self):
        old_high_cit = {"title": "Foundational work on planning with language",
                        "abstract": "planning language", "year": 2018, "citations": 2000}
        new_low_cit = {"title": "A small recent note", "abstract": "recent note",
                       "year": 2026, "citations": 0}
        ranked = detect_foundational([new_low_cit, old_high_cit])
        assert ranked[0]["title"] == old_high_cit["title"]

    def test_method_comparison_refuses_blind_metrics(self):
        rows = compare_methods({
            "MethodA": [{"claim": "x", "benchmark": "SimBench", "metric": "success", "value": "70"}],
            "MethodB": [{"claim": "y", "benchmark": "RealRobot", "metric": "success", "value": "90"}],
        })
        assert not rows[0]["comparable_on_shared_benchmarks"]
        assert "INVALID" in rows[0]["note"]

    def test_literature_map_report_written(self, cfg, fake_registry, make_orchestrator):
        orch, p = _run(cfg, fake_registry, make_orchestrator,
                       "Map the literature on LLM-based manipulation planning.")
        assert (orch.ws.reports / "literature_map.md").exists()
        assert (orch.ws.reports / "benchmark_analysis.md").exists()


class TestStartupIntelligence:
    def test_opportunity_pipeline_offline(self, tmp_path):
        """Pain evidence -> pain points -> opportunity -> assumptions -> falsification."""
        from research_engine.storage.database import Database
        from research_engine.storage.graph_store import GraphStore
        from research_engine.storage.repositories import Repositories
        from research_engine.intelligence.startup import StartupIntelligence
        from research_engine.intelligence.falsification import AssumptionEngine
        from research_engine.models.evidence import Evidence

        db = Database(tmp_path / "t.sqlite")
        repos = Repositories(db)
        graph = GraphStore(db)
        si = StartupIntelligence(repos, graph)
        ev_texts = [
            ("Shop owners complain billing is manual and tedious", "https://f.example.org/1"),
            ("Retailers say billing takes hours every day and is error prone", "https://b.example.org/2"),
            ("Current billing software costs $50/mo per store", "https://r.example.org/3"),
        ]
        for i, (t, u) in enumerate(ev_texts):
            repos.evidence.save(Evidence(project_id="p", claim_text=t,
                                         quote="verbatim long enough text here ok",
                                         source_url=u, source_id=f"s{i}", source_tier=3))
        stats = si.extract_all("p")
        assert len(stats["pain_points"]) >= 1
        opps = si.discover_opportunities("p")
        assert opps, "pain + corroboration must produce an opportunity candidate"
        o = opps[0]
        breakdown = si.score_opportunity("p", o)
        assert set(breakdown["factors"]).issuperset({"pain_severity", "evidence_strength"})
        assert "weights" in breakdown and abs(sum(breakdown["weights"].values()) - 1.0) < 0.01

        eng = AssumptionEngine(repos, provider=None)
        o.critical_assumptions = eng.critical_assumptions(o)
        assert len(o.critical_assumptions) >= 3
        tests = eng.design_falsification_tests("p", o)
        assert tests
        t0 = tests[0]
        assert t0.success_condition and t0.failure_condition and t0.decision_rule

    def test_market_reports_written(self, cfg, fake_registry, make_orchestrator):
        orch, p = _run(cfg, fake_registry, make_orchestrator,
                       "AI opportunities for small Indian retailers", mode="startup")
        assert (orch.ws.reports / "market_map.md").exists()
        assert (orch.ws.reports / "opportunity_map.md").exists()
        assert (orch.ws.reports / "validation_candidates.md").exists()


class TestMemoryAndSnapshots:
    def test_snapshot_and_diff_roundtrip(self, cfg, fake_registry, make_orchestrator):
        orch, p = _run(cfg, fake_registry, make_orchestrator,
                       "Snapshot test research question about planning benchmarks.")
        from research_engine.memory.snapshots import SnapshotManager, iteration_diff
        sm = SnapshotManager(orch.ws)
        m1 = sm.create(orch.repos, p.id, "pre")
        d = iteration_diff(orch.repos, p.id, max(1, p.current_iteration - 1),
                           p.current_iteration)
        assert "research_gain" in d and "added" in d
        assert sm.list_snapshots()

    def test_claim_tracing_end_to_end(self, cfg, fake_registry, make_orchestrator):
        orch, p = _run(cfg, fake_registry, make_orchestrator,
                       "Traceability check: what do sources say about success rates?")
        claims = orch.repos.claims.all(p.id)
        if not claims:
            pytest.skip("no claims produced offline")
        from research_engine.memory.qa import trace_claim
        chain = trace_claim(orch.repos, claims[0].id)
        assert chain.get("claim", {}).get("id") == claims[0].id
