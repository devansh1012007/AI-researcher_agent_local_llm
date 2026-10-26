"""INVARIANT-005: claim↔quote faithfulness (audit BUG-09 / P0-03).

Adversarial suite per stabilization spec §24-26: negation, numbers,
comparisons, causality, hedging, quantifiers, contrast-clause stripping.
"""
from __future__ import annotations

import pytest

from research_engine.pipeline.claim_support import (
    SUPPORT_FACTOR, verify_claim_support)


class TestMeaningInversion:
    def test_audit_canonical_case_rejected(self):
        """THE audit case: quote's second clause contradicts the claim."""
        r = verify_claim_support(
            "Revenue increased 5% and margins improved.",
            "Revenue increased 5%, although margins declined last quarter.")
        assert r.verdict == "CONTRADICTS", r.reasons

    def test_negation_flip(self):
        r = verify_claim_support(
            "The drug is effective for treating condition X.",
            "The trial found the drug is not effective for treating condition X.")
        assert r.verdict == "CONTRADICTS"

    def test_partial_quote_cannot_hide_failure(self):
        r = verify_claim_support(
            "The system works reliably in production.",
            "The system fails to work reliably under load, though demos looked fine.")
        assert r.verdict in ("CONTRADICTS", "WEAKLY_SUPPORTS")


class TestNumbers:
    def test_figure_mismatch_contradicts(self):
        r = verify_claim_support(
            "Adoption grew 12% year over year.",
            "Adoption grew 5% year over year according to the filing.")
        assert r.verdict == "CONTRADICTS"

    def test_matching_number_supported(self):
        r = verify_claim_support(
            "Adoption grew 12% year over year.",
            "Platform data shows adoption grew 12% year over year.")
        assert r.supports

    def test_claim_invents_absent_number_downgraded(self):
        r = verify_claim_support(
            "The platform processed 4 million transactions daily.",
            "The platform processes millions of transactions every day.")
        assert r.verdict in ("PARTIALLY_SUPPORTS", "WEAKLY_SUPPORTS")


class TestHedgingAndQuantifiers:
    def test_dropped_hedge_downgrades(self):
        r = verify_claim_support(
            "Vaccination reduces transmission risk.",
            "Vaccination may reduce transmission risk, early data suggests.")
        assert r.verdict == "WEAKLY_SUPPORTS"

    def test_up_to_tightening(self):
        r = verify_claim_support(
            "Users save 40% on costs with the tool.",
            "Users can save up to 40% on costs with the tool.")
        assert r.verdict in ("PARTIALLY_SUPPORTS", "WEAKLY_SUPPORTS")

    def test_correlation_not_promoted_to_causation(self):
        r = verify_claim_support(
            "Coffee consumption causes longer lifespans.",
            "The study found coffee consumption is associated with longer lifespans.")
        assert r.verdict == "WEAKLY_SUPPORTS"


class TestPositiveCases:
    def test_clean_entailment(self):
        r = verify_claim_support(
            "The battery charges to 80 percent in 15 minutes.",
            "Company claims the battery charges to 80 percent in 15 minutes "
            "under standard conditions.")
        assert r.verdict in ("ENTAILS", "STRONGLY_SUPPORTS")

    def test_paraphrase_strong_support(self):
        r = verify_claim_support(
            "Clinics reduced billing errors after switching.",
            "Practices that switched reported a reduction in billing errors.")
        assert r.supports

    def test_unrelated_rejected(self):
        r = verify_claim_support(
            "Quantum error rates improved dramatically this year.",
            "The restaurant expanded its menu to include vegan options.")
        assert r.verdict == "UNRELATED"


class TestIntegration:
    def test_support_factor_gates_synthesis_weight(self):
        """Only ENTAILS/STRONGLY/PARTIALLY feed grounded synthesis; a weak
        swarm cannot outvote one strongly-grounded source (P0-09 seam)."""
        assert SUPPORT_FACTOR["ENTAILS"] > SUPPORT_FACTOR["WEAKLY_SUPPORTS"] * 2
        assert SUPPORT_FACTOR["CONTRADICTS"] == 0.0
        assert SUPPORT_FACTOR["UNRELATED"] == 0.0

    def test_tier5_swarm_cannot_outvote_tier1(self):
        """INVARIANT-007 via aggregate_claim_strength: 10 tier-5 partials
        < 1 tier-1 entails."""
        from datetime import datetime, timezone
        from research_engine.models.enums import EvidenceStatus
        from research_engine.models.evidence import Claim, Evidence
        from research_engine.reasoning.evidence_quality import (
            aggregate_claim_strength)
        now = datetime.now(timezone.utc).isoformat()

        def ev(tier, conf, verdict):
            e = Evidence(project_id="p", claim_text="x", quote="y",
                         source_id="s", source_tier=tier, confidence=conf,
                         support_verdict=verdict, support_score=0.8,
                         status=EvidenceStatus.EXTRACTED,
                         published_date=now)
            e.ensure_id()
            return e

        claim = Claim(project_id="p", text="x")
        strong_one = aggregate_claim_strength(claim, [ev(1, 0.9, "ENTAILS")])
        swarm = aggregate_claim_strength(
            claim, [ev(5, 0.9, "PARTIALLY_SUPPORTS")] * 10)
        assert swarm.score < strong_one.score, \
            (swarm.components, strong_one.components)

    def test_status_mapping_fail_closed(self):
        from research_engine.models.enums import EvidenceStatus
        from research_engine.pipeline.claim_support import status_for_support
        assert status_for_support(EvidenceStatus.EXTRACTED, "CONTRADICTS") == \
            EvidenceStatus.REJECTED
        assert status_for_support(EvidenceStatus.EXTRACTED, "UNRELATED") == \
            EvidenceStatus.REJECTED
        assert status_for_support(EvidenceStatus.EXTRACTED, "NEUTRAL") == \
            EvidenceStatus.UNVERIFIED
        assert status_for_support(EvidenceStatus.EXTRACTED, "ENTAILS") == \
            EvidenceStatus.EXTRACTED


class TestHypothesisWeighting:
    def test_tier1_single_outranks_tier5_swarm(self):
        """INVARIANT-007 at the hypothesis layer (audit P0-09)."""
        import tempfile, pathlib
        from research_engine.models.evidence import Evidence
        from research_engine.models.reasoning import Hypothesis
        from research_engine.reasoning.hypothesis_engine import score_hypothesis
        from research_engine.storage.database import Database
        from research_engine.storage.repositories import Repositories
        from research_engine.storage.reasoning_repos import ReasoningRepos
        db = Database(pathlib.Path(tempfile.mkdtemp()) / "t.sqlite")
        repos, rr = Repositories(db), ReasoningRepos(db)

        def mk(tier, conf, verdict, n):
            e = Evidence(project_id="p", claim_text=f"claim {n}",
                         quote=f"quote {n}", source_id=f"s{n}",
                         source_tier=tier, confidence=conf,
                         support_verdict=verdict, status="EXTRACTED")
            e.ensure_id()
            repos.evidence.save(e)
            return e.id

        results = {}
        for tag, spec in [("strong", [(1, 0.9, "ENTAILS")]),
                          ("swarm", [(5, 0.9, "PARTIALLY_SUPPORTS")] * 10)]:
            h = Hypothesis(project_id="p", title=tag, statement=tag,
                           domain="scientific")
            h.ensure_id()
            rr.hypotheses.save(h)
            h.supporting_evidence = [mk(*s, i) for i, s in enumerate(spec)]
            rr.hypotheses.save(h)
            results[tag] = score_hypothesis(repos, rr, "p", h)

        assert results["swarm"]["support"] < results["strong"]["support"], \
            "tier-5 swarm must never outvote tier-1 primary"
