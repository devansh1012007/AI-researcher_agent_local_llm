"""System-level invariants (stabilization phase, spec §56).

INVARIANT-003 idempotency · INVARIANT-004 report purity · project isolation ·
INVARIANT-008 service boundaries · INVARIANT-010 opportunity schema ·
gate-priority formula pinning (kills audit mutation M-1).
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import pathlib

import pytest


QUESTION = ("Find promising startup opportunities in AI bookkeeping "
            "software for Indian SMB retailers")

EVIDENCE = [
    ("https://f.example.com/t1", "Retailers complain bookkeeping is manual "
     "and time-consuming weekly in spreadsheets", 5),
    ("https://n.example.com/x1", "Shop owners paying accountants 15000 rupees "
     "per month for basic bookkeeping", 4),
    ("https://c.example.com/z1", "Zoho Books charges $15 per month for small "
     "businesses", 3),
    ("https://c.example.com/z2", "Tally costs $300 annual license per seat", 3),
    ("https://g.example.com/g1", "New regulation mandates digital invoicing "
     "for retailers above turnover threshold from 2025", 2),
]


def _seeded(tmp_path):
    from research_engine.core.config import AppConfig
    from research_engine.core.orchestrator import Orchestrator
    cfg = AppConfig.load()
    cfg.storage.data_dir = str(tmp_path)
    cfg.search.web_provider = "none"
    cfg.search.academic_providers = []
    orch = Orchestrator.create_project(cfg, QUESTION, mode="startup")
    pid = orch.project.id
    from research_engine.models.evidence import Evidence
    from research_engine.models.research import Source
    srcs = {}
    for url, claim, tier in EVIDENCE:
        if url not in srcs:
            s = Source(project_id=pid, url=url, canonical_url=url,
                       domain=url.split("/")[2], title=url)
            s.ensure_id()
            orch.repos.sources.save(s)
            srcs[url] = s
        e = Evidence(project_id=pid, claim_text=claim, quote=claim[:70],
                     source_id=srcs[url].id, source_tier=tier,
                     status="EXTRACTED")
        e.ensure_id()
        orch.repos.evidence.save(e)
    return orch, cfg, tmp_path, pid


TABLES = ["startup_markets", "competitor_profiles", "pricing_plans",
          "startup_personas", "alternatives", "jtbd",
          "opportunity_decisions", "opportunities", "evidence", "claims",
          "hypotheses", "experiments", "assumptions2"]


def _snap(db_path):
    conn = sqlite3.connect(db_path)
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in TABLES}


class TestReportPurity:
    def test_generation_never_mutates_primary_state(self, tmp_path):
        """INVARIANT-004 (audit P0-10): two consecutive report generations
        on a completed project leave ALL primary tables byte-count stable."""
        orch, cfg, tmp, pid = _seeded(tmp_path)
        from research_engine.specialists.startup.service import StartupResearchService
        StartupResearchService(cfg=cfg, data_dir=str(tmp)).run_full_pipeline(pid)
        before = _snap(orch.ws.db_path)

        from research_engine.reports.generator import ReportGenerator
        gen = ReportGenerator(cfg, None, orch.repos, orch.ws)
        gen.generate_all(orch.project)
        mid = _snap(orch.ws.db_path)
        gen.generate_all(orch.project)
        after = _snap(orch.ws.db_path)
        assert before == mid == after, \
            f"report generation mutated state: {before} -> {mid} -> {after}"
        # derived artifacts DID appear
        assert (pathlib.Path(orch.ws.reports) / "startup_research.md").exists()


class TestProjectIsolation:
    def test_projects_cannot_read_each_other(self, tmp_path):
        orch_a, cfg, _, pid_a = _seeded(tmp_path)
        from research_engine.core.config import AppConfig
        from research_engine.core.orchestrator import Orchestrator
        from research_engine.models.evidence import Evidence
        from research_engine.models.research import Source
        s = Source(project_id="proj_b", url="https://b.example.com/1",
                   canonical_url="https://b.example.com/1",
                   domain="b.example.com", title="B secret evidence")
        s.ensure_id()
        b_orch = Orchestrator.create_project(cfg, "Question about project bee secrets",
                                             mode="academic")
        s.project_id = b_orch.project.id
        s.ensure_id()
        b_orch.repos.sources.save(s)
        e = Evidence(project_id=b_orch.project.id, claim_text="B-secret claim",
                     quote="B-secret claim", source_id=s.id, source_tier=3,
                     status="EXTRACTED")
        e.ensure_id()
        b_orch.repos.evidence.save(e)

        # A's repos see nothing from B
        ids_a = {x.id for x in orch_a.repos.evidence.all(pid_a)}
        evs_b = b_orch.repos.evidence.all(b_orch.project.id)
        assert all(x.id not in ids_a for x in evs_b)
        # FTS search scoped to A returns no B content
        hits = orch_a.repos.db.fts_search(pid_a, "B-secret")
        assert not hits


class TestOpportunitySchema:
    def test_canonical_scores_carry_schema_version(self, tmp_path):
        orch, cfg, tmp, pid = _seeded(tmp_path)
        from research_engine.specialists.startup.service import StartupResearchService
        svc = StartupResearchService(cfg=cfg, data_dir=str(tmp))
        svc.run_mode(pid, "OPPORTUNITY_DISCOVERY")
        opps = orch.repos.opportunities.all(pid)
        assert opps, "discovery produced opportunities"
        for o in opps:
            sb = o.score_breakdown or {}
            assert sb.get("schema_version") == 2, (
                f"{o.id} missing canonical schema version")
            assert set(sb.get("weights", {})) >= {"pain_severity",
                                                  "wtp_evidence"}
        # INVARIANT-010: one canonical schema in the store after canonical runs
        versions = {(o.score_breakdown or {}).get("schema_version")
                    for o in opps}
        assert versions == {2}

    def test_gate_priority_formula_pinned(self):
        """KILLS AUDIT MUTATION M-1 (`missing<=2` -> `<=9`): priority is high
        ONLY at <=2 missing dimensions AND non-weak demand signals."""
        from research_engine.specialists.startup.opportunities import (
            OpportunityEngine)
        from research_engine.storage.reasoning_repos import ReasoningRepos

        class _E:
            def get(self, eid):
                return None
        class _R:
            evidence = _E()
            @staticmethod
            def all(pid):
                return []
        eng = OpportunityEngine(_R(), ReasoningRepos.__new__(ReasoningRepos))

        base_ctx = {
            "market": None, "segments": [], "pains": [], "alternatives": [],
            "competitor_profiles": [], "pricing_plans": [],
            "size_report": {}, "distribution_difficulty": {},
            "whynow": {}, "tech_shifts": [], "retention_signals": [],
            "moat_candidates": [], "counterevidence_searched": True,
            "assumptions_built": True, "validation_designed": True,
        }
        opp = type("O", (), {"evidence_ids": ["ev_1"],
                             "current_alternative": "excel",
                             "notes": ""})()

        full = dict(base_ctx, market=type("M", (), {"definition_gaps": []})(),
                    segments=[{"name": "smb", "evidence_ids": ["ev_1"]}],
                    pains=[{"evidence_id": "ev_1"}],
                    alternatives=[type("A", (), {"used_by_segments": []})()],
                    competitor_profiles=[type("C", (), {"classification": "direct"})()],
                    pricing_plans=[type("P", (), {"evidence_id": "ev_1"})()],
                    whynow={"verdict": "supported"})
        strong_demand = {"pain_severity": 0.8, "wtp_evidence": 0.7,
                         "economic_value": 0.6}
        weak_demand = {"pain_severity": 0.2, "wtp_evidence": 0.2,
                       "economic_value": 0.0}

        g_full_strong = eng.quality_gate("p", opp, full, factors=strong_demand)
        assert g_full_strong["priority"] == "high"

        g_gaps_strong = eng.quality_gate(
            "p", opp,
            dict(full, competitor_profiles=[], pricing_plans=[], whynow={}),
            factors=strong_demand)
        assert g_gaps_strong["priority"] in ("medium", "low"), \
            ">2 missing dims must NOT be high"

        g_hype = eng.quality_gate("p", opp, full, factors=weak_demand)
        assert g_hype["priority"] != "high", \
            "weak demand must never be high even with full coverage"


class TestServiceBoundaries:
    def test_interfaces_do_not_touch_storage_directly(self):
        """INVARIANT-008 executable guard: API/MCP never construct storage
        bundles or mutate the state machine. CLI allows exactly two legacy
        loader helpers (_load2/_load3) that hand READ handles to platform
        components (graph/literature tooling) — tracked as shrinking debt."""
        import re
        root = pathlib.Path(__file__).parents[2] / "src" / "research_engine"
        forbidden = [r"Repositories\(", r"ReasoningRepos\(", r"GraphStore\(",
                     r"\.sm\.transition\("]
        violations = []

        def scan(rel, skip_ranges=()):
            text = (root / rel).read_text()
            for pat in forbidden:
                for m in re.finditer(pat, text):
                    line = text[:m.start()].count("\n") + 1
                    if any(a <= line <= b for a, b in skip_ranges):
                        continue
                    violations.append(f"{rel}:{line}: {pat}")

        # api + mcp: zero tolerance
        scan("api/app.py")
        scan("mcp_server/server.py")
        # cli: allowlist ONLY the bodies of the two loader helpers
        cli_text = (root / "cli/main.py").read_text()

        def helper_span(name):
            start = cli_text.index(f"def {name}(")
            nxt = cli_text.find("\ndef ", start + 1)
            return (cli_text[:start].count("\n") + 1,
                    cli_text[:nxt].count("\n") + 1)
        spans = [helper_span("_load2"), helper_span("_load3")]
        for pat in forbidden:
            for m in re.finditer(pat, cli_text):
                line = cli_text[:m.start()].count("\n") + 1
                if any(a <= line <= b for a, b in spans):
                    continue
                violations.append(f"cli/main.py:{line}: {pat}")
        assert not violations, f"service-boundary violations: {violations}"

    def test_startup_assumption_register_via_service(self, tmp_path):
        """CLI assumptions/next route through the specialist, not raw repos."""
        orch, cfg, tmp, pid = _seeded(tmp_path)
        from research_engine.specialists.startup.service import StartupResearchService
        svc = StartupResearchService(cfg=cfg, data_dir=str(tmp))
        svc.run_mode(pid, "OPPORTUNITY_DISCOVERY")
        svc.run_mode(pid, "VALIDATION_PLANNING")
        rr = svc._repos_for(svc._orch(pid))[2]
        asm = sorted(rr.assumptions.all(pid), key=lambda a: -a.priority)
        assert asm
        assert all(a.opportunity_id for a in asm)
