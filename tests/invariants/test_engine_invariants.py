"""Invariant tests for Configurable Research Engines (INV-030 through INV-035)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_engine.engines.loader import (
    EngineValidationError,
    get_engine,
    validate_manifest,
)
from research_engine.engines.manifest import EngineManifest
from research_engine.engines.schema import DomainSchemaError, validate_domain_schema_dict
from research_engine.models.enums import EvidenceStatus, SourceType
from research_engine.models.evidence import Claim, Evidence
from research_engine.models.opportunity import Opportunity
from research_engine.models.project import ResearchProblem, ResearchProject
from research_engine.models.questions import Question
from research_engine.pipeline.questions import answer_question, filter_valid_questions
from research_engine.services.trail_service import TrailService
from research_engine.specialists.startup.opportunities import OpportunityEngine
from research_engine.storage.database import Database
from research_engine.storage.reasoning_repos import ReasoningRepos
from research_engine.storage.repositories import Repositories
from research_engine.specialists.startup.repos import StartupRepos


def test_inv_030_mode_equivalence_and_manifest_single_source_of_truth():
    """INV-030: Built-in academic and startup engine manifests are the single source of truth for modes."""
    from research_engine.modes.base import get_mode
    for name in ("academic", "startup"):
        mode = get_mode(name)
        manifest = get_engine(name)
        assert mode.name == manifest.name
        assert mode.display_name == manifest.display_name
        assert mode.branch_categories == manifest.branch_categories()
        assert mode.evidence_schema_hint == manifest.extraction.schema_hint
        assert mode.report_files == manifest.report_files()
        assert mode.source_preferences == manifest.planning.source_preferences


def test_inv_031_engine_manifest_cannot_disable_verification_or_egress_locks():
    """INV-031: Engine manifests cannot bypass quote verification, claim support, or local-only egress."""
    raw = json.loads(get_engine("academic").model_dump_json())
    raw["safety"]["allow_skip_quote_verification"] = True
    errs, _ = validate_manifest(EngineManifest.model_validate(raw))
    assert errs

    raw2 = json.loads(get_engine("academic").model_dump_json())
    raw2["loop"]["per_iteration"] = [
        {"step": "search"},
        {"step": "fetch_and_parse"},
        {"step": "extract_evidence"},
        {"step": "evaluate_convergence"},
    ]
    errs2, _ = validate_manifest(EngineManifest.model_validate(raw2))
    assert any("verify_and_dedup" in e for e in errs2)


def test_inv_032_user_questions_require_changes_and_record_tier2_user_observation(tmp_path: Path):
    """INV-032: Questions without `changes` are dropped; user answers are tier-2 USER_OBSERVATION."""
    assert filter_valid_questions([Question(project_id="p", text="Why?", changes="")]) == []

    db = Database(tmp_path / "inv032.db")
    repos = Repositories(db)
    p = ResearchProject(id="p_inv032", question_raw="Q", mode="academic")
    repos.projects.save(p)
    prob = ResearchProblem(project_id=p.id, objective="Q", research_question="Q")
    prob.ensure_id()
    repos.problems.save(prob)
    q = Question(
        project_id=p.id,
        text="What benchmark?",
        changes="Selects benchmark family",
        default_assumption="MMLU",
    )
    repos.questions.save(q)
    answered = answer_question(repos, p.id, q.id, answer_text="SWE-bench Verified")
    src = repos.sources.get(answered.source_id)
    ev = repos.evidence.get(answered.evidence_id)
    assert src is not None and ev is not None
    assert src.source_type == SourceType.USER_OBSERVATION and src.source_tier == 2
    assert ev.source_type == SourceType.USER_OBSERVATION and ev.source_tier == 2


def test_inv_033_negative_trail_preserves_rejected_evidence_and_single_source_claims(tmp_path: Path):
    """INV-033: Negative trail surfaces rejected evidence and single-source claims."""
    db = Database(tmp_path / "inv033.db")
    repos = Repositories(db)
    p = ResearchProject(id="p_inv033", question_raw="Q", mode="academic")
    repos.projects.save(p)
    ev_rej = Evidence(
        id="ev_r1",
        project_id=p.id,
        claim_text="Bad claim",
        quote="Missing quote",
        source_id="src_1",
        status=EvidenceStatus.REJECTED,
        validation_notes="quote not found",
    )
    ev_ok = Evidence(
        id="ev_o1",
        project_id=p.id,
        claim_text="Good claim",
        quote="Exact quote from text",
        source_id="src_1",
        status=EvidenceStatus.SUPPORTED,
    )
    repos.evidence.save(ev_rej)
    repos.evidence.save(ev_ok)
    clm = Claim(id="clm_s1", project_id=p.id, text="Good claim", supported_by=["ev_o1"], confidence=0.7)
    repos.claims.save(clm)

    trail = TrailService(repos, None, p).build_trail(p.id)
    assert any(r["evidence_id"] == "ev_r1" for r in trail["negative_trail"]["rejected_evidence"])
    assert any(c["claim_id"] == "clm_s1" for c in trail["negative_trail"]["single_source_claims"])


def test_inv_034_startup_pack_enforces_counterevidence_and_decision_contract(tmp_path: Path):
    """INV-034: Startup engine pack enforces counterevidence lock and decision output contract."""
    m = get_engine("startup")
    assert m.safety.require_counterevidence_for_opportunities is True

    raw = json.loads(m.model_dump_json())
    raw["safety"]["require_counterevidence_for_opportunities"] = False
    errs, _ = validate_manifest(EngineManifest.model_validate(raw))
    assert any("require_counterevidence_for_opportunities" in e for e in errs)

    # Verify OpportunityEngine counter_evidence_pair surfaces supporting + counter evidence
    db = Database(tmp_path / "inv034.db")
    repos = Repositories(db)
    srepos = StartupRepos(db)
    rrepos = ReasoningRepos(db)
    oe = OpportunityEngine(repos, srepos, rrepos)
    opp = Opportunity(
        id="opp_1",
        project_id="p_st",
        problem="Manual invoice reconciliation pain",
        customer_segment="SMB retailers",
        supporting_evidence=["ev_sup1"],
        counter_evidence=["ev_con1"],
    )
    repos.opportunities.save(opp)
    pair = oe.counter_evidence_pair("p_st", opp)
    assert "strongest_argument_for" in pair and "strongest_argument_against" in pair and "negative_evidence" in pair


def test_inv_035_domain_schema_forbids_external_or_internal_ref():
    """INV-035: Domain schemas reject any $ref to prevent SSRF / local file inclusion."""
    with pytest.raises(DomainSchemaError, match="forbidden \\$ref"):
        validate_domain_schema_dict({
            "type": "object",
            "properties": {
                "x": {"$ref": "file:///etc/passwd"}
            },
        })
