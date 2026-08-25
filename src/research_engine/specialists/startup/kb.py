"""Cross-project market knowledge base (spec #93-95).

A market researched once becomes reusable: competitors, segments, pricing,
regulation and signals persist under a stable market slug in
`<data_dir>/startup_kb/market_kb.sqlite` and are copied into any later
project researching the same market, so only MISSING information is fetched.

Implementation note: reuses the standard Database schema with
project_id = "kb:<market_slug>" — zero new persistence machinery.
"""
from __future__ import annotations

import pathlib

from research_engine.specialists.startup.market import slugify
from research_engine.specialists.startup.models import (
    CompetitorProfile, DistributionChannel, Market, PricingPlan)
from research_engine.specialists.startup.repos import StartupRepos
from research_engine.storage.database import Database


class MarketKnowledgeBase:
    def __init__(self, data_dir: str | pathlib.Path):
        root = pathlib.Path(data_dir) / "startup_kb"
        root.mkdir(parents=True, exist_ok=True)
        self.db = Database(root / "market_kb.sqlite")

    @staticmethod
    def pid(slug: str) -> str:
        return f"kb:{slugify(slug)}"

    # ------------------------------------------------------------- write side
    def remember_market(self, market: Market,
                        competitors: list[CompetitorProfile] | None = None,
                        pricing_plans: list[PricingPlan] | None = None,
                        channels: list[DistributionChannel] | None = None) -> str:
        pid = self.pid(market.market_slug or market.name)
        clone = market.model_copy(update={"project_id": pid})
        if not clone.id:
            clone.ensure_id()
        sr = StartupRepos(self.db)
        sr.markets.save(clone)
        for c in competitors or []:
            cc = c.model_copy(update={"project_id": pid})
            if not cc.id:
                cc.ensure_id()
            sr.competitor_profiles.save(cc)
        for p in pricing_plans or []:
            pp = p.model_copy(update={"project_id": pid})
            if not pp.id:
                pp.ensure_id()
            sr.pricing_plans.save(pp)
        for ch in channels or []:
            dch = ch.model_copy(update={"project_id": pid})
            if not dch.id:
                dch.ensure_id()
            sr.distribution_channels.save(dch)
        return pid

    # ------------------------------------------------------------- read side
    def lookup(self, market_name_or_slug: str) -> dict:
        """Return reusable knowledge for the market, or empty dict."""
        slug = slugify(market_name_or_slug)
        pid = self.pid(slug)
        sr = StartupRepos(self.db)
        markets = sr.markets.all(pid)
        if not markets:
            return {}
        return {
            "project_key": pid,
            "markets": markets,
            "competitors": sr.competitor_profiles.all(pid),
            "pricing_plans": sr.pricing_plans.all(pid),
            "distribution_channels": sr.distribution_channels.all(pid),
        }

    def freshness_summary(self, kb_entry: dict, today: str = "") -> dict:
        """Per-kind freshness of remembered knowledge (spec #63)."""
        from research_engine.specialists.startup.policies import freshness_state
        out = {"markets": "fresh", "competitors": [], "pricing": []}
        for c in kb_entry.get("competitors", []):
            obs = ""
            evs = getattr(c, "evidence_ids", []) or []
            out["competitors"].append({"name": c.name,
                                       "state": freshness_state("competitor", obs, today)})
        for p in kb_entry.get("pricing_plans", []):
            out["pricing"].append({
                "raw": p.price_raw,
                "state": freshness_state("pricing", getattr(p, "observed_at", ""), today)})
        return out

    # ------------------------------------------------------------- reuse side
    def seed_project(self, project_id: str, market_name_or_slug: str,
                     project_srepos: StartupRepos) -> int:
        """Copy remembered market knowledge into a fresh project (returns count).
        IDEMPOTENT: entities already present in the project (by natural key)
        are skipped, so repeated seeding cannot duplicate rows (spec #93)."""
        entry = self.lookup(market_name_or_slug)
        if not entry:
            return 0
        n = 0
        have_markets = {m.market_slug for m in
                        project_srepos.markets.all(project_id)}
        have_comps = {c.name.lower() for c in
                      project_srepos.competitor_profiles.all(project_id)}
        have_plans = {(p.competitor_name.lower(), p.price_raw, p.billing_period)
                      for p in project_srepos.pricing_plans.all(project_id)}
        have_chans = {ch.name.lower() for ch in
                      project_srepos.distribution_channels.all(project_id)}
        for m in entry["markets"]:
            if m.market_slug in have_markets:
                continue
            mc = m.model_copy(update={"id": "", "project_id": project_id})
            mc.ensure_id()
            project_srepos.markets.save(mc)
            n += 1
        for c in entry["competitors"]:
            if c.name.lower() in have_comps:
                continue
            cc = c.model_copy(update={"id": "", "project_id": project_id})
            cc.ensure_id()
            project_srepos.competitor_profiles.save(cc)
            n += 1
        for p in entry["pricing_plans"]:
            key = (p.competitor_name.lower(), p.price_raw, p.billing_period)
            if key in have_plans:
                continue
            pc = p.model_copy(update={"id": "", "project_id": project_id})
            pc.ensure_id()
            project_srepos.pricing_plans.save(pc)
            n += 1
        for ch in entry["distribution_channels"]:
            if ch.name.lower() in have_chans:
                continue
            dc = ch.model_copy(update={"id": "", "project_id": project_id})
            dc.ensure_id()
            project_srepos.distribution_channels.save(dc)
            n += 1
        return n
