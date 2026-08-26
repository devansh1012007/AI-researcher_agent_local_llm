"""Specialist extension contract (gate §49-50) + INV-014.

POSITIVE fixture: a hypothetical new specialist using ONLY canonical seams.
The platform must enforce identity, grounding, ownership and score semantics
automatically along that path.

NEGATIVE fixtures: the same specialist implemented incorrectly. Each test
proves an EXISTING mechanism catches the violation. A negative fixture that
stops being caught is a readiness regression.

INV-014 auditors are DETECTORS by phase decision (see
specialists/extension_audit.py); they become runtime enforcement when
finding F-03's provenance carve-out is settled.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest


def _startup_project(tmp_path):
    from research_engine.core.config import AppConfig
    from research_engine.core.orchestrator import Orchestrator
    cfg = AppConfig.load()
    cfg.storage.data_dir = str(tmp_path)
    cfg.search.web_provider = "none"
    cfg.search.academic_providers = []
    orch = Orchestrator.create_project(
        cfg, "Startup research: invoicing software for freelance designers",
        mode="startup")
    return orch, cfg, orch.project.id


# ------------------------------------------------------------- positive

class TestCompliantSpecialist:
    """A specialist that follows the contract gets everything for free."""

    def test_identity_grounding_ownership_and_scores(self, tmp_path):
        # -- entity identity via natural-key upsert ----------------------
        orch, cfg, pid = _startup_project(tmp_path)
        from research_engine.specialists.startup.models import CompetitorProfile
        from research_engine.specialists.startup.repos import get_startup_repos
        srepos = get_startup_repos(orch)

        first = CompetitorProfile(project_id=pid, name="FreshBooks",
                                  product="invoicing")
        first.ensure_id()
        saved = srepos.competitor_profiles.save_natural(first)

        variant = CompetitorProfile(project_id=pid, name="freshbooks inc",
                                    product="invoicing",
                                    weaknesses=["slow support"])
        variant.ensure_id()
        resaved = srepos.competitor_profiles.save_natural(variant)

        rows = srepos.competitor_profiles.all(pid)
        assert len(rows) == 1 and rows[0].id == saved.id == resaved.id
        assert "slow support" in rows[0].weaknesses  # merge kept original id

        # -- grounding: both gates before persistence --------------------
        from research_engine.models.evidence import Evidence
        from research_engine.models.research import Source
        from research_engine.pipeline.claim_support import verify_claim_support
        from research_engine.pipeline.evidence import verify_quote

        src = Source(project_id=pid,
                     url="https://pricing.example.com/freshbooks",
                     canonical_url="https://pricing.example.com/freshbooks",
                     domain="pricing.example.com", title="FreshBooks pricing")
        src.ensure_id()
        orch.repos.sources.save(src)

        claim = "FreshBooks charges 15 dollars per month for the Plus plan"
        quote = "The Plus plan costs 15 dollars per month."
        ok, _ = verify_quote(quote, chunk_text=quote + " Billed annually.")
        verdict = verify_claim_support(claim, quote)
        assert ok and verdict.verdict in ("SUPPORTS", "STRONGLY_SUPPORTS")

        ev = Evidence(project_id=pid, claim_text=claim, quote=quote,
                      source_id=src.id, source_tier=2,
                      status="SUPPORTED", support_verdict=verdict.verdict)
        ev.ensure_id()
        orch.repos.evidence.save(ev)

        from research_engine.specialists.extension_audit import (
            ungrounded_evidence)
        assert ungrounded_evidence(orch.db, pid) == []

        # -- long-running task inherits fencing --------------------------
        from research_engine.models.job import ResearchJob, JobTask
        from research_engine.storage.platform_db import PlatformDB, \
            StaleTaskOwner

        db = PlatformDB(pathlib.Path(cfg.storage.data_dir))
        job = ResearchJob(project_id=pid, type="maintenance")
        db.save_job(job)
        db.add_task(JobTask(job_id=job.id, type="WORK",
                            resource_profile="WORK", max_attempts=2))
        task = db.claim_next_task("spec_worker", {"WORK": 1}, 60.0)
        assert task is not None
        fence = db.get_task(task.id).attempts
        finished = db.finish_task(task.id, "spec_worker", ok=True,
                                  fence=fence, result={"ok": True})
        assert finished.status == "SUCCEEDED"

        # stale writer rejected automatically
        with pytest.raises(StaleTaskOwner):
            db.finish_task(task.id, "stale_worker", ok=True,
                           fence=fence, result={"evil": True})

    def test_report_writer_can_be_pure(self, tmp_path):
        """A compliant report writer derives output without touching state."""
        orch, cfg, pid = _startup_project(tmp_path)
        stores = [pathlib.Path(orch.ws.db_path)]
        from research_engine.specialists.extension_audit import (
            store_fingerprint)
        before = store_fingerprint(stores)

        lines = ["# Specialist report (derived)"]
        for o in orch.repos.opportunities.all(pid):
            lines.append(f"- {o.problem} score={o.score}")
        report = "\n".join(lines)

        out = tmp_path / "reports" / "specialist_report.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text(report)

        assert store_fingerprint(stores) == before
        assert out.exists() and out.read_text().startswith("# Specialist")


# ------------------------------------------------------------- negative

class TestBrokenSpecialistIsCaught:
    """Gate §50: each incorrect implementation meets a tripwire."""

    def test_duplicate_plain_save_hits_unique_index(self, tmp_path):
        orch, _, pid = _startup_project(tmp_path)
        from research_engine.specialists.startup.models import CompetitorProfile
        from research_engine.specialists.startup.repos import get_startup_repos
        srepos = get_startup_repos(orch)

        a = CompetitorProfile(project_id=pid, name="FreshBooks")
        a.ensure_id()
        srepos.competitor_profiles.save_natural(a)

        b = CompetitorProfile(project_id=pid, name="FreshBooks")
        b.ensure_id()
        with pytest.raises(Exception) as excinfo:
            srepos.competitor_profiles.save(b)  # bypassed natural key
        assert "unique" in str(excinfo.value).lower(), str(excinfo.value)

    def test_ungrounded_evidence_flagged_by_auditor(self, tmp_path):
        orch, _, pid = _startup_project(tmp_path)
        from research_engine.models.evidence import Evidence
        from research_engine.models.enums import SourceType

        ev = Evidence(project_id=pid,
                      claim_text="Competitor X is failing badly",
                      quote="", source_id="", source_tier=5,
                      source_type=SourceType.OTHER, status="SUPPORTED")
        ev.ensure_id()
        orch.repos.evidence.save(ev)  # storage accepts; detector catches

        from research_engine.specialists.extension_audit import (
            ungrounded_evidence)
        flagged = ungrounded_evidence(orch.db, pid)
        ids = {f["id"] for f in flagged}
        assert ev.id in ids
        reasons = " | ".join(r for f in flagged if f["id"] == ev.id
                             for r in f["reasons"])
        assert "without support_verdict" in reasons and "empty quote" in reasons

    def test_experiment_carveout_is_allowlisted_explicitly(self, tmp_path):
        """The ONLY exempt provenance is the documented experiment carve-out
        (finding F-03); it must stay visible, never silently extended."""
        orch, _, pid = _startup_project(tmp_path)
        from research_engine.models.evidence import Evidence
        from research_engine.models.enums import SourceType

        ev = Evidence(project_id=pid, claim_text="A/B result",
                      quote="conversion improved to 9%", source_id="",
                      source_tier=1, source_type=SourceType.EXPERIMENT_RESULT,
                      status="SUPPORTED")
        ev.ensure_id()
        orch.repos.evidence.save(ev)

        from research_engine.specialists.extension_audit import (
            GROUNDED_EXEMPT_SOURCE_TYPES, ungrounded_evidence)
        assert "experiment_result" in GROUNDED_EXEMPT_SOURCE_TYPES
        assert all(f["id"] != ev.id for f in ungrounded_evidence(orch.db, pid))

    def test_mutating_report_detected_by_fingerprint_guard(self, tmp_path):
        """Detector teeth: a 'report' function that sneaks a write trips the
        purity guard even though row counts would look identical."""
        orch, cfg, pid = _startup_project(tmp_path)
        from research_engine.specialists.extension_audit import (
            store_fingerprint)
        stores = [pathlib.Path(orch.ws.db_path)]

        def bad_report_writer():
            from research_engine.models.evidence import Evidence
            e = Evidence(project_id=pid, claim_text="sneaky",
                         quote="x" * 40, source_id="", source_tier=5,
                         status="EXTRACTED")
            e.ensure_id()
            orch.repos.evidence.save(e)
            return "# report"

        before = store_fingerprint(stores)
        bad_report_writer()
        assert store_fingerprint(stores) != before, \
            "purity guard failed to detect mutation"

    def test_opaque_score_rejected_by_schema_validator(self):
        from research_engine.specialists.extension_audit import (
            validate_score_schema)

        problems = validate_score_schema({"score": 82})
        assert any("schema_version" in p for p in problems)
        assert any("factors" in p or "opaque" in p for p in problems)

        problems = validate_score_schema({
            "schema_version": 2, "total": 0.62,
            "factors": {"pain_severity": 0.8, "spend_signal": 0.4},
            "reasons": {"pain_severity": "3 linked pains",
                        "spend_signal": "explicit spend statements"},
            "labels": {}, "weights": {}, "gate": {"priority": "MEDIUM"}})
        assert problems == []

        # factor without a reason is caught even under correct version
        problems = validate_score_schema(
            {"schema_version": 2, "factors": {"pain_severity": 0.8},
             "reasons": {}})
        assert any("pain_severity" in p for p in problems)


# ------------------------------------------------------------- INV-014 scan

class TestInv014StaticScan:
    """Static half of INV-014: specialists extend the platform through the
    repo/service seams; they do not open databases themselves."""

    ALLOWED = {
        "kb.py",           # documented cross-project KB store (own Database)
        "data_repair.py",  # maintenance tool operating on a passed-in handle
        "extension_audit.py",  # INV-014 auditor: read-only cross-project scans
    }

    FORBIDDEN = (r"\bDatabase\(", r"\bsqlite3\.connect\(", r"\.upsert\(")

    def test_specialists_do_not_open_storage_themselves(self):
        root = (pathlib.Path(__file__).resolve().parents[2] /
                "src" / "research_engine" / "specialists")
        violations = []
        for p in sorted(root.rglob("*.py")):
            if p.name in self.ALLOWED:
                continue
            text = p.read_text()
            for pat in self.FORBIDDEN:
                for i, line in enumerate(text.splitlines(), 1):
                    if "__all__" in line or line.lstrip().startswith("#"):
                        continue
                    import re
                    if re.search(pat, line):
                        violations.append(f"{p.relative_to(root)}:{i}: {pat}")
        assert not violations, (
            "INV-014 violation — specialists must use canonical repos/seams: "
            + "; ".join(violations))
