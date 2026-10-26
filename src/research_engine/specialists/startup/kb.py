"""Cross-project market knowledge base (spec #93-95, Phase 8).

A market researched once becomes reusable: competitors, segments, pricing,
regulation and signals persist under a stable market slug in
`<data_dir>/startup_kb/market_kb.sqlite` and are also mirrored into the
domain-agnostic `RelationalKnowledgeBase` (`<data_dir>/_global/relational_kb.sqlite`).
"""
from __future__ import annotations

import pathlib

from research_engine.memory.relational_kb import RelationalKnowledgeBase
from research_engine.specialists.startup.market import slugify
from research_engine.specialists.startup.models import (
    CompetitorProfile,
    DistributionChannel,
    Market,
    PricingPlan,
)
from research_engine.specialists.startup.repos import StartupRepos
from research_engine.storage.database import Database


class MarketKnowledgeBase:
    def __init__(self, data_dir: str | pathlib.Path):
        self.data_dir = pathlib.Path(data_dir)
        root = self.data_dir / "startup_kb"
        root.mkdir(parents=True, exist_ok=True)
        self.db = Database(root / "market_kb.sqlite")
        self.relational_kb = RelationalKnowledgeBase(self.data_dir)

    @staticmethod
    def pid(slug: str) -> str:
        return f"kb:{slugify(slug)}"

    # ------------------------------------------------------------- write side
    def remember_market(
        self,
        market: Market,
        competitors: list[CompetitorProfile] | None = None,
        pricing_plans: list[PricingPlan] | None = None,
        channels: list[DistributionChannel] | None = None,
    ) -> str:
        slug = slugify(market.market_slug or market.name)
        pid = self.pid(slug)
        ns = f"startup:{slug}"
        clone = market.model_copy(update={"project_id": pid})
        if not clone.id:
            clone.ensure_id()
        sr = StartupRepos(self.db)
        sr.markets.save(clone)

        mkt_ent = self.relational_kb.upsert_entity(
            namespace=ns,
            entity_type="market",
            natural_key=slug,
            name=market.name or slug,
            attributes={"definition": market.definition, "geography": market.geography},
            project_id=market.project_id or pid,
        )

        comp_ent_by_name: dict[str, str] = {}
        for c in competitors or []:
            cc = c.model_copy(update={"project_id": pid})
            if not cc.id:
                cc.ensure_id()
            sr.competitor_profiles.save(cc)
            c_ent = self.relational_kb.upsert_entity(
                namespace=ns,
                entity_type="competitor",
                natural_key=c.name.lower(),
                name=c.name,
                attributes={"classification": c.classification, "positioning": c.positioning},
                project_id=c.project_id or pid,
                observed_at=str(getattr(c, "observed_at", "") or ""),
            )
            comp_ent_by_name[c.name.lower()] = c_ent["id"]
            self.relational_kb.link_entities(
                namespace=ns,
                from_entity_id=c_ent["id"],
                relation_type="operates_in",
                to_entity_id=mkt_ent["id"],
                project_id=c.project_id or pid,
            )

        for p in pricing_plans or []:
            pp = p.model_copy(update={"project_id": pid})
            if not pp.id:
                pp.ensure_id()
            sr.pricing_plans.save(pp)
            p_key = f"{p.competitor_name.lower()}:{p.price_raw}:{p.billing_period}"
            p_ent = self.relational_kb.upsert_entity(
                namespace=ns,
                entity_type="pricing_plan",
                natural_key=p_key,
                name=f"{p.competitor_name} {p.price_raw}",
                attributes={
                    "competitor_name": p.competitor_name,
                    "price_raw": p.price_raw,
                    "billing_period": p.billing_period,
                },
                project_id=p.project_id or pid,
                observed_at=str(getattr(p, "observed_at", "") or ""),
            )
            comp_id = comp_ent_by_name.get(p.competitor_name.lower())
            if comp_id:
                self.relational_kb.link_entities(
                    namespace=ns,
                    from_entity_id=comp_id,
                    relation_type="offers_plan",
                    to_entity_id=p_ent["id"],
                    project_id=p.project_id or pid,
                )

        for ch in channels or []:
            dch = ch.model_copy(update={"project_id": pid})
            if not dch.id:
                dch.ensure_id()
            sr.distribution_channels.save(dch)
            ch_ent = self.relational_kb.upsert_entity(
                namespace=ns,
                entity_type="distribution_channel",
                natural_key=ch.name.lower(),
                name=ch.name,
                attributes={"channel_type": getattr(ch, "channel_type", "")},
                project_id=ch.project_id or pid,
            )
            self.relational_kb.link_entities(
                namespace=ns,
                from_entity_id=mkt_ent["id"],
                relation_type="uses_channel",
                to_entity_id=ch_ent["id"],
                project_id=ch.project_id or pid,
            )
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
        """Per-kind freshness of remembered knowledge (spec #63, Phase 6.2)."""
        from datetime import date
        from research_engine.specialists.startup.policies import freshness_state

        today_str = today or date.today().isoformat()
        mkts = kb_entry.get("markets", [])
        mkt_obs = ""
        if mkts:
            m0 = mkts[0]
            mkt_obs = str(getattr(m0, "updated_at", "") or getattr(m0, "created_at", ""))[:10]
        out = {
            "markets": freshness_state("market_size", mkt_obs, today_str) if mkt_obs else "fresh",
            "competitors": [],
            "pricing": [],
        }
        for c in kb_entry.get("competitors", []):
            obs = str(
                getattr(c, "observed_at", "")
                or getattr(c, "updated_at", "")
                or getattr(c, "created_at", "")
            )[:10]
            out["competitors"].append(
                {
                    "name": c.name,
                    "observed_at": obs,
                    "state": freshness_state("competitor", obs, today_str),
                }
            )
        for p in kb_entry.get("pricing_plans", []):
            obs = str(
                getattr(p, "observed_at", "")
                or getattr(p, "updated_at", "")
                or getattr(p, "created_at", "")
            )[:10]
            out["pricing"].append(
                {
                    "raw": p.price_raw,
                    "observed_at": obs,
                    "state": freshness_state("pricing", obs, today_str),
                }
            )
        return out

    # ------------------------------------------------------------- reuse side
    def seed_project(
        self,
        project_id: str,
        market_name_or_slug: str,
        project_srepos: StartupRepos,
    ) -> int:
        """Copy remembered market knowledge into a fresh project (returns count).
        IDEMPOTENT: entities already present in the project (by natural key)
        are skipped, so repeated seeding cannot duplicate rows (spec #93)."""
        entry = self.lookup(market_name_or_slug)
        if not entry:
            return 0
        n = 0
        have_markets = {m.market_slug for m in project_srepos.markets.all(project_id)}
        have_comps = {c.name.lower() for c in project_srepos.competitor_profiles.all(project_id)}
        have_plans = {
            (p.competitor_name.lower(), p.price_raw, p.billing_period)
            for p in project_srepos.pricing_plans.all(project_id)
        }
        have_chans = {ch.name.lower() for ch in project_srepos.distribution_channels.all(project_id)}
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
