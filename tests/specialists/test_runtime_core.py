"""Phase 5 §3–§18: specialist runtime core — registry, contract,
permissions, budgets, grounding-through-API, perf registry."""
from __future__ import annotations

import pathlib
import tempfile

import pytest


def _cfg(tmp_path):
    from research_engine.core.config import AppConfig
    cfg = AppConfig.load()
    cfg.storage.data_dir = str(tmp_path)
    cfg.search.web_provider = "none"
    cfg.search.academic_providers = []
    return cfg


def _orch(tmp_path):
    from research_engine.core.orchestrator import Orchestrator
    orch = Orchestrator.create_project(
        _cfg(tmp_path), "Cross-domain question about robotic grippers",
        mode="academic")
    return orch


def _desc(sid="probe", version="1.0", **kw):
    from research_engine.specialists.runtime import (
        SpecialistBudget, SpecialistDescriptor)
    if "modes" in kw:
        kw["supported_modes"] = kw.pop("modes")
    base = dict(specialist_id=sid, name="Probe", version=version,
                supported_modes=["ANALYZE"], entity_types=["widget"],
                skills=["probe_skill"])
    base.update(kw)
    if "budgets" not in base:
        base["budgets"] = SpecialistBudget(max_llm_calls=2)
    return SpecialistDescriptor(**base)


def _invoke(output_overrides=None):
    from research_engine.specialists.runtime import SpecialistOutput

    def invoke(ctx):
        d = dict(specialist_id="probe")
        if output_overrides:
            d.update(output_overrides)
        return SpecialistOutput(**d)
    return invoke


# ------------------------------------------------------------- registry

class TestRegistry:
    def setup_method(self):
        from research_engine.specialists.runtime import reset_registry
        reset_registry()

    def test_register_lookup_and_latest_version(self):
        from research_engine.specialists.runtime import get_registry
        reg = get_registry()
        reg.register(_desc("probe", "1.0"), _invoke())
        reg.register(_desc("probe", "1.1"), _invoke())
        assert reg.lookup("probe").descriptor.version == "1.1"
        assert reg.versions("probe") == ["1.0", "1.1"]
        assert reg.lookup("probe", "1.0").descriptor.version == "1.0"

    def test_duplicate_key_rejected(self):
        from research_engine.specialists.runtime import get_registry
        reg = get_registry()
        reg.register(_desc(), _invoke())
        with pytest.raises(ValueError):
            reg.register(_desc(), _invoke())

    def test_retire_keeps_history_visible(self):
        from research_engine.specialists.runtime import (
            HealthState, LifecycleState, get_registry)
        reg = get_registry()
        reg.register(_desc("oldie", "0.9"), _invoke())
        assert reg.retire("oldie", "0.9", reason="superseded by 1.0") is True
        r = reg.lookup("oldie", "0.9")
        assert r.health.state == HealthState.RETIRED
        assert r.lifecycle == LifecycleState.COMPLETED
        assert r.history and r.history[-1][1] == "superseded by 1.0"
        # retired specialists vanish from active listings but stay resolvable
        assert all(d.specialist_id != "oldie"
                   for d in reg.list_active()) or reg.list_active() == []
        assert reg.lookup("oldie", "0.9") is r

    def test_capability_query_filters(self):
        from research_engine.specialists.runtime import (
            SpecialistPermission, get_registry)
        reg = get_registry()
        reg.register(_desc("a", modes=["MARKET"]), _invoke())
        reg.register(_desc("b", modes=["FEASIBILITY"],
                           entity_types=["method"]), _invoke())
        got = [d.specialist_id for d in reg.capability_query(
            modes=["FEASIBILITY"])]
        assert got == ["b"]
        # default permissions are read-only: nothing claims CREATE_*
        assert reg.capability_query(
            permission=SpecialistPermission.CREATE_EVIDENCE) == []
        from research_engine.specialists.runtime import SpecialistPermission
        writer = _desc("w", permissions={
            SpecialistPermission.READ_PROJECT,
            SpecialistPermission.CREATE_EVIDENCE})
        reg.register(writer, _invoke())
        assert [d.specialist_id for d in reg.capability_query(
            permission=SpecialistPermission.CREATE_EVIDENCE)] == ["w"]


# ------------------------------------------------------------ budget/perm

class TestInvocationGuards:
    def test_llm_budget_hard_stops(self):
        from research_engine.specialists.runtime import (
            BudgetExceeded, InvocationBudget, SpecialistBudget)
        b = InvocationBudget(SpecialistBudget(max_llm_calls=2))
        b.spend_llm_call()
        b.spend_llm_call()
        with pytest.raises(BudgetExceeded):
            b.spend_llm_call()

    def test_permission_denied(self, tmp_path):
        from research_engine.specialists.api import PermissionDenied
        from research_engine.specialists.runtime import InvocationBudget
        orch = _orch(tmp_path)
        api = SpecialistApiForTest(orch, perms=set(),
                                   specialist_id="locked")
        with pytest.raises(PermissionDenied):
            api.read_evidence()


def SpecialistApiForTest(orch, perms, specialist_id):
    from research_engine.specialists.api import SpecialistApi
    from research_engine.specialists.runtime import InvocationBudget
    return SpecialistApi(orch, perms, InvocationBudget(), specialist_id, "1.0")


# ------------------------------------------------------------------- API

class TestGroundedEvidenceViaApi:
    def test_supported_passes_both_gates(self, tmp_path):
        from research_engine.models.research import Source
        orch = _orch(tmp_path)
        api = SpecialistApiForTest(orch, perms={
            "READ_PROJECT", "READ_EVIDENCE", "CREATE_EVIDENCE",
            "CREATE_CLAIM", "CREATE_GAP"}, specialist_id="writer")
        s = Source(project_id=orch.project.id,
                   url="https://x.example.com/a",
                   canonical_url="https://x.example.com/a",
                   domain="x.example.com", title="t")
        s.ensure_id()
        orch.repos.sources.save(s)

        claim = "The gripper lifts 5 kg payloads"
        quote = "The gripper lifts 5 kg payloads in tests."
        res = api.create_evidence(claim_text=claim, quote=quote,
                                  chunk_text=quote + " More context.",
                                  source_id=s.id, source_tier=2)
        assert res["status"] == "SUPPORTED"
        saved = orch.repos.evidence.all(orch.project.id)[-1]
        assert saved.support_verdict in ("SUPPORTS", "STRONGLY_SUPPORTS")

    def test_contradicting_quote_persisted_rejected(self, tmp_path):
        """The direction-flip case currently yields a non-CONTRADICTS verdict
        (gate finding F-06), so the facade's fail-closed mapping cannot fire.
        Strict-xfail tied to F-06: flips to REJECTED when the lexicon gap
        is fixed."""
        from research_engine.models.enums import EvidenceStatus
        from research_engine.models.research import Source
        orch = _orch(tmp_path)
        api = SpecialistApiForTest(orch, perms={"CREATE_EVIDENCE"},
                                   specialist_id="writer")
        s = Source(project_id=orch.project.id,
                   url="https://x.example.com/b",
                   canonical_url="https://x.example.com/b",
                   domain="x.example.com", title="t")
        s.ensure_id()
        orch.repos.sources.save(s)
        res = api.create_evidence(
            claim_text="Churn decreased after redesign",
            quote="Churn increased after the onboarding redesign.",
            chunk_text="Churn increased after the onboarding redesign.",
            source_id=s.id, source_tier=3)
        assert res["status"] == "REJECTED"
        row = orch.repos.evidence.all(orch.project.id)[-1]
        assert row.status == EvidenceStatus.REJECTED

    test_contradicting_quote_persisted_rejected = pytest.mark.xfail(
        strict=True,
        reason="GATE F-06: antonym/direction inversion undetected upstream")(
            test_contradicting_quote_persisted_rejected)

    def test_bad_quote_not_persisted(self, tmp_path):
        from research_engine.models.research import Source
        orch = _orch(tmp_path)
        api = SpecialistApiForTest(orch, perms={"CREATE_EVIDENCE"},
                                   specialist_id="writer")
        s = Source(project_id=orch.project.id,
                   url="https://x.example.com/c",
                   canonical_url="https://x.example.com/c",
                   domain="x.example.com", title="t")
        s.ensure_id()
        orch.repos.sources.save(s)
        res = api.create_evidence(claim_text="Anything at all here ok",
                                  quote="totally unrelated words appear",
                                  chunk_text="different content entirely!!",
                                  source_id=s.id, source_tier=4)
        assert res["status"] == "REJECTED_QUOTE"
        assert res["evidence"] is None

    def test_ungrounded_write_is_impossible_by_schema(self, tmp_path):
        """§76 partial: the facade has no raw-evidence escape hatch."""
        api = SpecialistApiForTest(_orch(tmp_path),
                                   perms={"CREATE_EVIDENCE"},
                                   specialist_id="w")
        assert not hasattr(api, "save_raw_evidence")
        assert not hasattr(api, "execute_sql")


# ------------------------------------------------------------------- perf

class TestPerfRegistry:
    def test_natural_key_accumulation(self, tmp_path=None):
        from research_engine.storage.platform_db import PlatformDB
        db = PlatformDB(pathlib.Path(tempfile.mkdtemp()) / "d")
        for i, (ok, lat) in enumerate([(True, 2.0), (True, 6.0),
                                       (False, 4.0)]):
            db.record_specialist_perf("tech", "1.0", "FEASIBILITY",
                                      ok=ok, latency_s=lat, llm_calls=i + 1)
        rows = db.list_specialist_perf("tech")
        assert len(rows) == 1
        r = rows[0]
        assert r["runs"] == 3 and r["failures"] == 1
        assert r["llm_calls"] == 6
        assert 0 < r["avg_latency_s"] < 6.0  # EMA, recent dominates
