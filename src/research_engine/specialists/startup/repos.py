"""Persistence for startup domain entities.

Follows the established pattern: tables are declared in
storage/database.py::_EXTRA_TABLES; repos are thin _GenericRepo subclasses
bundled in StartupRepos (mirrors ReasoningRepos).

INVARIANT-003: every repo declares its NATURAL KEY. Persistence goes through
save_natural() -> resolve existing row -> merge -> keep original identity.
Fresh ids are minted only for genuinely new entities.
"""
from __future__ import annotations

import re

from research_engine.models.startup import FalsificationTest
from research_engine.specialists.startup.identity import norm_name
from research_engine.specialists.startup.models import (
    CompetitorProfile, CurrentAlternative, DistributionChannel,
    JobToBeDone, Market, MarketSizeEstimate, OpportunityDecision,
    OpportunityVersion, Persona, PricingPlan, TechnologyShift)
from research_engine.storage.reasoning_repos import _GenericRepo


class _FTRepo(_GenericRepo):
    """falsification_tests rows (table predates this package)."""
    table = "falsification_tests"
    model = FalsificationTest


class MarketRepo(_GenericRepo):
    table = "startup_markets"
    model = Market

    def _index_cols(self, entity):
        return {"market_slug": entity.market_slug}

    def natural_key(self, entity):
        return {"market_slug": entity.market_slug}


class MarketSizeRepo(_GenericRepo):
    table = "market_sizes"
    model = MarketSizeEstimate

    def _index_cols(self, entity):
        return {"market_id": entity.market_id}

    def natural_key(self, entity):
        # one attributed figure per source evidence
        return {"evidence_id": entity.evidence_id}


class PersonaRepo(_GenericRepo):
    table = "startup_personas"
    model = Persona

    def natural_key(self, entity):
        return {"segment_id": entity.segment_id}


class JTBDRepo(_GenericRepo):
    table = "jtbd"
    model = JobToBeDone

    def _index_cols(self, entity):
        return {"segment_id": entity.segment_id}

    def natural_key(self, entity):
        return {"segment_id": entity.segment_id}


class AlternativeRepo(_GenericRepo):
    table = "alternatives"
    model = CurrentAlternative

    def natural_key(self, entity):
        # conservative normalization; compared in Python below because
        # suffix-stripping normalization is not expressible in SQL
        return {"name": entity.name}

    def find_by_natural_key(self, project_id: str, key_cols: dict) -> object | None:
        target = norm_name(key_cols.get("name", ""))
        if not target:
            return None
        for row in self.all(project_id):
            if norm_name(row.name) == target:
                return row
        return None


class CompetitorProfileRepo(_GenericRepo):
    table = "competitor_profiles"
    model = CompetitorProfile

    def _index_cols(self, entity):
        # INVARIANT-003: the indexed identity IS the normalized name, so the
        # database-level unique constraint enforces normalized uniqueness
        return {"name_lower": norm_name(entity.name),
                "classification": entity.classification}

    def natural_key(self, entity):
        return {"name_lower": norm_name(entity.name)}


class PricingPlanRepo(_GenericRepo):
    table = "pricing_plans"
    model = PricingPlan

    def _index_cols(self, entity):
        return {"competitor_name": entity.competitor_name}

    def natural_key(self, entity):
        return {"competitor_name": entity.competitor_name,
                "price_raw": entity.price_raw,
                "billing_period": entity.billing_period}


class DistributionChannelRepo(_GenericRepo):
    table = "distribution_channels"
    model = DistributionChannel

    def natural_key(self, entity):
        return {"name": entity.name}


class TechShiftRepo(_GenericRepo):
    table = "tech_shifts"
    model = TechnologyShift
    # cross-call dedupe happens in SignalAnalyzer.detect_tech_shifts via
    # desc_fingerprint scan; no single-field natural key exists.


class OpportunityVersionRepo(_GenericRepo):
    table = "opportunity_versions"
    model = OpportunityVersion

    def _index_cols(self, entity):
        return {"opportunity_id": entity.opportunity_id,
                "version": entity.version}

    def history(self, project_id: str, opportunity_id: str) -> list:
        rows = self.all(project_id)
        return sorted((r for r in rows if r.opportunity_id == opportunity_id),
                      key=lambda r: r.version)


class OpportunityDecisionRepo(_GenericRepo):
    table = "opportunity_decisions"
    model = OpportunityDecision

    def _index_cols(self, entity):
        return {"opportunity_id": entity.opportunity_id,
                "decision": entity.decision}

    def for_opportunity(self, project_id: str, opportunity_id: str) -> list:
        rows = [r for r in self.all(project_id) if r.opportunity_id == opportunity_id]
        return sorted(rows, key=lambda r: r.created_at)
    # append-only history: content-level dedupe lives in
    # OpportunityEngine.record_decision (same-day identical entries collapse).


def get_startup_repos(orch):
    """Idiom used by services: cache the bundle on the orchestrator."""
    if not hasattr(orch, "_srepos"):
        orch._srepos = StartupRepos(orch.db)
    return orch._srepos


class StartupRepos:
    """Bundle of startup-domain repos bound to one per-project Database."""

    def __init__(self, db):
        self.db = db
        self.markets = MarketRepo(db)
        self.market_sizes = MarketSizeRepo(db)
        self.personas = PersonaRepo(db)
        self.jtbd = JTBDRepo(db)
        self.alternatives = AlternativeRepo(db)
        self.competitor_profiles = CompetitorProfileRepo(db)
        self.pricing_plans = PricingPlanRepo(db)
        self.distribution_channels = DistributionChannelRepo(db)
        self.tech_shifts = TechShiftRepo(db)
        self.opportunity_versions = OpportunityVersionRepo(db)
        self.opportunity_decisions = OpportunityDecisionRepo(db)
        self.falsification_tests = _FTRepo(db)
