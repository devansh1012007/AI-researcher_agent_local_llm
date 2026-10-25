"""Phase 5 tests: P3-1 through P3-9 research quality & benchmark integrity."""
from __future__ import annotations

from pathlib import Path
import pytest

from evals.metrics.eval_metrics import score_project
from research_engine.core.orchestrator import Orchestrator
from research_engine.models.document import DocumentChunk
from research_engine.models.enums import ClaimKind, EvidenceStatus
from research_engine.models.evidence import Claim, Evidence
from research_engine.models.project import ResearchMetrics
from research_engine.models.reasoning import Assumption, Experiment, Hypothesis
from research_engine.pipeline.evidence import EvidenceWorker
from research_engine.reasoning.hypothesis_engine import (
    HypothesisCritic, HypothesisLifecycle, RefinementLoop, rank_hypotheses,
    score_hypothesis,
)
from research_engine.specialists.startup.decisions import DecisionEngine
from research_engine.specialists.startup.opportunities import OpportunityEngine
from research_engine.specialists.startup.policies import pain_evidence_class
from research_engine.storage.database import Database
from research_engine.storage.reasoning_repos import ReasoningRepos
from research_engine.storage.repositories import Repositories


def test_p3_1_citation_coverage_and_report_citation_coverage(tmp_path):
    """P3-1: citation_coverage checks claim->quote-verified evidence;
    report_citation_coverage checks rendered info.md factual bullets."""
    db = Database(tmp_path / "db.sqlite")
    repos = Repositories(db)
    pid = "proj_cit"

    chunk = DocumentChunk(
        id="chk_1", project_id=pid, document_id="doc_1", sequence=0,
        text="Empirical evaluation shows retrieval augmented generation reduces hallucination rates by 42 percent.",
    )
    repos.chunks.save(chunk)

    ev_ok = Evidence(
        id="ev_ok1", project_id=pid, chunk_id="chk_1", document_id="doc_1",
        source_id="src_1", source_url="https://example.org/1",
        claim_text="RAG reduces hallucination rates by 42 percent.",
        quote="retrieval augmented generation reduces hallucination rates by 42 percent",
        status=EvidenceStatus.SUPPORTED,
    )
    repos.evidence.save(ev_ok)

    clm_supported = Claim(
        id="clm_1", project_id=pid, text="RAG reduces hallucination rates by 42%.",
        kind=ClaimKind.FACT, supported_by=["ev_ok1"], confidence=0.9,
    )
    clm_unsupported = Claim(
        id="clm_2", project_id=pid, text="Uncited claim without verified evidence.",
        kind=ClaimKind.FACT, supported_by=[], confidence=0.3,
    )
    repos.claims.save(clm_supported)
    repos.claims.save(clm_unsupported)

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "info.md").write_text("\n".join([
        "# Research Report — info.md",
        "",
        "## Key Findings",
        "",
        "#### Evidence-backed findings",
        "",
        "- **RAG reduces hallucination rates by 42%.** (confidence 0.90) — sources: [ev_ok1](https://example.org/1) tier:2",
        "- **Uncited claim in rendered report.** (confidence 0.30) — sources: n/a",
    ]), encoding="utf-8")

    scores = score_project(repos, pid)
    assert scores.citation_coverage == 0.5
    assert scores.report_citation_coverage == 0.5

    (reports_dir / "info.md").write_text("\n".join([
        "# Research Report — info.md",
        "",
        "## Key Findings",
        "",
        "#### Evidence-backed findings",
        "",
        "- **Uncited claim A.** (confidence 0.90) — sources: n/a",
        "- **Uncited claim B.** (confidence 0.30) — sources: n/a",
    ]), encoding="utf-8")
    scores_uncited = score_project(repos, pid)
    assert scores_uncited.citation_coverage == 0.5
    assert scores_uncited.report_citation_coverage == 0.0


def test_p3_2_research_gain_ignores_duplicate_quote_reingestion(tmp_path):
    """P3-2: duplicate evidence quotes in later iterations must not inflate research_gain."""
    db = Database(tmp_path / "db.sqlite")
    repos = Repositories(db)
    pid = "proj_gain"

    e1 = Evidence(project_id=pid, claim_text="c1", quote="unique quote number one about market",
                  source_id="s1", status=EvidenceStatus.SUPPORTED, iteration=1)
    e2 = Evidence(project_id=pid, claim_text="c2", quote="unique quote number two about pricing",
                  source_id="s2", status=EvidenceStatus.SUPPORTED, iteration=1)
    e1.ensure_id(); e2.ensure_id()
    repos.evidence.save(e1); repos.evidence.save(e2)

    for i in range(4):
        edup = Evidence(project_id=pid, claim_text="c1 dup", quote="unique quote number one about market",
                        source_id=f"s_dup_{i}", status=EvidenceStatus.SUPPORTED, iteration=2)
        edup.ensure_id()
        repos.evidence.save(edup)

    m1 = ResearchMetrics(project_id=pid, iteration=1, evidence_created=2, evidence_rejected=0,
                         new_claims_this_iter=2, gaps_resolved=0, duplicate_rate=0.0,
                         source_diversity_domains=2)
    m2 = ResearchMetrics(project_id=pid, iteration=2, evidence_created=6, evidence_rejected=0,
                         new_claims_this_iter=0, gaps_resolved=0, duplicate_rate=1.0,
                         source_diversity_domains=2)
    m1.ensure_id(); m2.ensure_id()
    repos.metrics.save(m1); repos.metrics.save(m2)

    assert Orchestrator._research_gain(m1, m2) == 0
    scores = score_project(repos, pid)
    assert scores.research_gain_by_iteration == [0]
    assert scores.research_gain_total == 0


def test_p3_3_consolidate_claims_dup_count_persisted_on_metrics(tmp_path):
    """P3-3: consolidate_claims dup_count is wired into ResearchMetrics.duplicate_claims."""
    from research_engine.core.config import AppConfig
    cfg = AppConfig.load()
    cfg.storage.data_dir = str(tmp_path)
    cfg.search.web_provider = "none"
    cfg.search.academic_providers = []
    orch = Orchestrator.create_project(cfg, "Question for duplicate claims wiring test", mode="academic")
    pid = orch.project.id

    ev1 = Evidence(project_id=pid, claim_text="Retrieval augmented generation improves factual accuracy.",
                   quote="Retrieval augmented generation improves factual accuracy in QA.",
                   source_id="s1", status=EvidenceStatus.SUPPORTED, iteration=1)
    ev2 = Evidence(project_id=pid, claim_text="Retrieval augmented generation improves factual accuracy!",
                   quote="Independent study shows RAG improves factual accuracy.",
                   source_id="s2", status=EvidenceStatus.SUPPORTED, iteration=1)
    ev1.ensure_id(); ev2.ensure_id()
    orch.repos.evidence.save(ev1); orch.repos.evidence.save(ev2)

    worker = EvidenceWorker(cfg, orch.router.extractor, orch.repos)
    new_c, dup_c = worker.consolidate_claims(pid, [ev1, ev2], iteration=1)
    assert new_c == 1
    assert dup_c == 1

    orch._dup_claims_by_iter = {1: dup_c}
    m = orch._compute_metrics(1)
    assert m.duplicate_claims_this_iter == 1
    assert m.duplicate_claims == 1


def test_p3_4_and_p3_5_and_p3_8_hypothesis_scoring_lifecycle_and_ranking(tmp_path):
    """P3-4: unsupported hypothesis confidence <= 0.25.
    P3-5: RefinementLoop transitions status via HypothesisLifecycle.
    P3-8: rank_hypotheses breaks ties deterministically by content key, not mint order."""
    db = Database(tmp_path / "db.sqlite")
    repos = Repositories(db)
    rrepos = ReasoningRepos(db)
    pid = "proj_hyp"

    h_alpha = Hypothesis(
        project_id=pid, title="Zeta title", statement="Alpha mechanism explains the gap.",
        type="CAUSAL", status="PROPOSED", origin="gap",
        predictions=["pred 1"], falsification_conditions=["If X fails in controlled test, falsified"],
    )
    h_beta = Hypothesis(
        project_id=pid, title="Alpha title", statement="Beta mechanism explains the gap.",
        type="CAUSAL", status="PROPOSED", origin="gap",
        predictions=["pred 1"], falsification_conditions=["If Y fails in controlled test, falsified"],
    )
    h_beta.ensure_id()
    h_alpha.ensure_id()
    rrepos.hypotheses.save(h_beta)
    rrepos.hypotheses.save(h_alpha)

    score_hypothesis(repos, rrepos, pid, h_beta)
    score_hypothesis(repos, rrepos, pid, h_alpha)
    assert h_alpha.confidence <= 0.25
    assert h_beta.confidence <= 0.25

    ranked = rank_hypotheses(repos, rrepos, pid, objective="balanced")
    assert [r["hypothesis"].id for r in ranked] == [h_alpha.id, h_beta.id]

    lifecycle = HypothesisLifecycle(rrepos)
    critic = HypothesisCritic(repos, rrepos, None)
    loop = RefinementLoop(repos, rrepos, None, lifecycle, critic)
    loop.run(pid, h_alpha)
    reloaded = rrepos.hypotheses.get(h_alpha.id)
    assert reloaded.status in ("UNDER_REVIEW", "NEEDS_EVIDENCE", "REFINED")
    assert rrepos.hypothesis_versions.history(pid, h_alpha.id)


def test_p3_6_pain_evidence_class_separates_vendor_funding_from_customer_payment():
    """P3-6: vendor funding/valuation announcements must never classify as actual_payment."""
    funding_claim = "BookkeepAI raised $25M Series A funding and was invoiced for automated payment software."
    assert pain_evidence_class(funding_claim) == "reported_pain"

    valuation_claim = "Competitor X was valued at $1.2B after its seed round for payment processing."
    assert pain_evidence_class(valuation_claim) == "reported_pain"

    real_payment_claim = "Small retailers paid $150 per month and were invoiced $1,800 annually for bookkeeping."
    assert pain_evidence_class(real_payment_claim) == "actual_payment"


def test_p3_7_p4_opportunity_strength_derived_from_evidence(tmp_path):
    """P3-7: P4 pattern strength varies deterministically with signal strength and pain hierarchy weight."""
    db = Database(tmp_path / "db.sqlite")
    repos = Repositories(db)
    rrepos = ReasoningRepos(db)
    eng = OpportunityEngine(repos, rrepos)

    ctx_med = {
        "pains": [
            {"statement": "Manual GST reconciliation takes hours", "evidence_id": "ev_1",
             "categories": ["time"], "evidence_class": "reported_pain",
             "frequency_signal": False, "hierarchy_weight": 0.2},
            {"statement": "Inventory errors occur in spreadsheets", "evidence_id": "ev_2",
             "categories": ["quality_problems"], "evidence_class": "reported_pain",
             "frequency_signal": False, "hierarchy_weight": 0.2},
        ],
        "tech_shifts": [],
        "signals": [{"kind": "funding", "strength": "MEDIUM", "evidence_ids": ["ev_f1"]}],
        "segments": [{"name": "kirana stores", "evidence_ids": ["ev_s1"]}],
        "alternatives": [],
    }
    ctx_strong = {
        "pains": [
            {"statement": "Manual GST reconciliation takes hours", "evidence_id": "ev_1",
             "categories": ["time"], "evidence_class": "existing_spending",
             "frequency_signal": False, "hierarchy_weight": 0.8},
            {"statement": "Inventory errors occur in spreadsheets", "evidence_id": "ev_2",
             "categories": ["quality_problems"], "evidence_class": "reported_pain",
             "frequency_signal": False, "hierarchy_weight": 0.2},
        ],
        "tech_shifts": [],
        "signals": [{"kind": "funding", "strength": "STRONG", "evidence_ids": ["ev_f1", "ev_f2"]}],
        "segments": [{"name": "kirana stores", "evidence_ids": ["ev_s1", "ev_s2", "ev_s3"]}],
        "alternatives": [],
    }
    p_med = [p for p in eng.detect_patterns("p", ctx_med)
             if p["pattern"] == "P4_attention_signal_unserved_segment"][0]
    p_strong = [p for p in eng.detect_patterns("p", ctx_strong)
                if p["pattern"] == "P4_attention_signal_unserved_segment"][0]
    assert p_strong["strength"] > p_med["strength"]
    assert 0.25 <= p_med["strength"] <= 0.65
    assert 0.25 <= p_strong["strength"] <= 0.65


def test_p3_9_readiness_scopes_experiments_to_opportunity_id(tmp_path):
    """P3-9: experiments belonging to Opportunity A must not advance Opportunity B to VALIDATION_READY."""
    from research_engine.specialists.startup.policies import QUALITY_GATE_REQUIREMENTS

    db = Database(tmp_path / "db.sqlite")
    repos = Repositories(db)
    rrepos = ReasoningRepos(db)
    pid = "proj_ready"

    full_gate = {"checks": {req: True for req in QUALITY_GATE_REQUIREMENTS}}

    asm_a = Assumption(project_id=pid, opportunity_id="opp_A", hypothesis_id="hyp_A",
                       statement="Retailers will pay $20/mo", kind="critical", status="unverified")
    asm_b = Assumption(project_id=pid, opportunity_id="opp_B", hypothesis_id="hyp_B",
                       statement="Clinics will switch from paper", kind="critical", status="unverified")
    asm_a.ensure_id(); asm_b.ensure_id()
    rrepos.assumptions.save(asm_a); rrepos.assumptions.save(asm_b)

    exp_a = Experiment(project_id=pid, hypothesis_id="hyp_A", opportunity_id="opp_A",
                       title="Preorder test for opp_A", status="DESIGNED")
    exp_a.ensure_id()
    rrepos.experiments.save(exp_a)

    dec = DecisionEngine(repos, rrepos)
    ready_a = dec.readiness(pid, opportunity_id="opp_A", gate=full_gate)
    ready_b = dec.readiness(pid, opportunity_id="opp_B", gate=full_gate)

    assert ready_a["level"] == "VALIDATION_READY"
    assert ready_b["level"] == "RESEARCH_READY", (
        f"Opportunity B without experiments was wrongly promoted to {ready_b['level']}"
    )
