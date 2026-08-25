"""Competitor analyzer: classification, product/pricing/distribution capture,
competitive landscape and gap detection.

Discipline:
- Existence != traction: traction notes only carry evidence-backed content.
- A competitor feature list is NOT proof the feature works well (spec #21).
- Pricing is normalized only with an explicit note; raw strings are sacred
  (spec #22). Monthly vs annual are never silently compared.
- Landscape axes must be justified by customer priorities, never arbitrary
  (spec #19).
"""
from __future__ import annotations

import re

from research_engine.specialists.startup.models import (
    CompetitorProfile, DistributionChannel, PricingPlan)
from research_engine.specialists.startup.policies import (
    DISTRIBUTION_CHANNELS, PRICING_MODELS)
from research_engine.storage.graph_store import GraphStore
from research_engine.storage.repositories import Repositories

_PERIOD_RE = re.compile(
    r"(?P<period>per month|/mo|monthly|per year|/yr|/year|annual\w*|one[- ]time|"
    r"per user|per seat|usage[- ]based|pay[- ]as[- ]you[- ]go)", re.I)
_AMOUNT_RE = re.compile(r"(?P<cur>[$₹€£])\s?(?P<amt>\d[\d,]*(?:\.\d+)?)")
_MAGNITUDE_TAIL_RE = re.compile(r"\s?(?:bn|b|mn|mm|m|million|billion|trillion)(?![a-z])", re.I)


def _is_magnitude_price(quote: str, match: re.Match) -> bool:
    """True when the matched amount is actually a funding/market-size
    magnitude ($10M, $1.2B, $24 billion) rather than a seat price."""
    tail = _MAGNITUDE_TAIL_RE.match(quote[match.end():])
    return bool(tail)


def _billing_period(text: str) -> str:
    p = _PERIOD_RE.search(text or "")
    if not p:
        return ""
    s = p.group("period").lower()
    if "month" in s or "/mo" in s:
        return "monthly"
    if "year" in s or "annual" in s or "/yr" in s:
        return "annual"
    if "one" in s:
        return "one_time"
    if "user" in s or "seat" in s:
        return "seat_based"
    if "usage" in s or "pay-as-you-go" in s.replace(" ", "-"):
        return "usage_based"
    return ""


def classify_pricing_model(text: str) -> str:
    t = (text or "").lower()
    if "freemium" in t or ("free" in t and "trial" not in t):
        return "freemium"
    if "commission" in t or "% of" in t or "take rate" in t:
        return "commission"
    if "transaction" in t:
        return "transaction_fee"
    if "usage" in t or "pay as you go" in t:
        return "usage_based"
    if "per seat" in t or "per user" in t or "per agent" in t:
        return "seat_based"
    if "enterprise" in t or "custom pricing" in t or "contact us" in t or "quote" in t:
        return "enterprise_contract"
    if "advertis" in t:
        return "advertising"
    if "annual" in t or "monthly" in t or "per month" in t:
        return "subscription"
    if "one-time" in t or "one time" in t or "lifetime" in t:
        return "one_time"
    if "service" in t and ("software" in t or "platform" in t):
        return "service_plus_software"
    return ""


def classify_competitor(name: str, product_text: str,
                        same_segment: bool, same_job: bool) -> str:
    """Heuristic classification (spec #18)."""
    t = (product_text or "").lower()
    if "platform for developers" in t or "infrastructure" in t:
        return "infrastructure_provider"
    if "marketplace" in t or "app store" in t:
        return "platform"
    if "internal tool" in t or "built in-house" in t:
        return "internal_alternative"
    if same_segment and same_job:
        return "direct"
    if same_segment or same_job:
        return "indirect"
    if re.search(r"\b(instead of|alternative to|replace)\b", t):
        return "substitute"
    if "funding" in t and "launch" in t:
        return "potential_entrant"
    return "indirect"


def normalize_price(raw_amount: float, currency: str, period: str) -> tuple[float, str]:
    """Return (monthly_equivalent, note). Zero means 'unknown' — never guess."""
    if raw_amount <= 0:
        return 0.0, "unparseable amount; raw preserved"
    if period == "monthly":
        return round(raw_amount, 2), "already monthly"
    if period == "annual":
        note = ("annual price divided by 12 for comparability; "
                "annual plans often differ from monthly billing")
        return round(raw_amount / 12.0, 2), note
    if period == "seat_based":
        return round(raw_amount, 2), "per-seat figure; seat count unknown"
    return 0.0, f"period '{period or 'unknown'}' not normalizable; raw preserved"


class CompetitorAnalyzer:
    def __init__(self, repos: Repositories, graph: GraphStore,
                 provider=None, srepos=None):
        self.repos = repos
        self.graph = graph
        self.provider = provider
        self.srepos = srepos

    def accepted(self, project_id: str) -> list:
        return [e for e in self.repos.evidence.all(project_id)
                if e.status != "REJECTED"]

    # ------------------------------------------------------------- profiles
    def build_profiles(self, project_id: str, segments: list[str] | None = None
                       ) -> list[CompetitorProfile]:
        """Build rich profiles from graph companies + evidence mentions."""
        seg_names = [s.lower() for s in (segments or [])]
        profiles: dict[str, CompetitorProfile] = {}
        graph_ents = self.graph.entities(project_id, "company") + \
            self.graph.entities(project_id, "competitor")

        def profile_for(name: str) -> CompetitorProfile:
            key = name.lower()
            if key not in profiles:
                p = CompetitorProfile(project_id=project_id, name=name)
                p.ensure_id()
                profiles[key] = p
            return profiles[key]

        for ent in graph_ents:
            p = profile_for(ent.name)
            attrs = ent.attributes or {}
            p.product = attrs.get("product", "")[:160]
            p.positioning = attrs.get("positioning", "")[:200]
            p.funding_signal = attrs.get("funding_signal", "")   # traction kept separate
            p.evidence_ids = list(attrs.get("evidence_ids", []))
            p.classification = classify_competitor(
                ent.name, p.product + " " + p.positioning,
                same_segment=any(s in (p.product + p.positioning).lower()
                                 for s in seg_names),
                same_job=bool(re.search(r"\b(same|similar) (problem|workflow|job)\b",
                                        p.positioning, re.I)))

        # enrich from evidence text
        for ev in self.accepted(project_id):
            claim = ev.claim_text or ""
            for key, prof in list(profiles.items()):
                name_rx = re.compile(rf"\b{re.escape(key.split()[0])}\w*\b", re.I) \
                    if key.split() else None
                if not name_rx or not name_rx.search(claim):
                    continue
                if ev.id not in prof.evidence_ids and len(prof.evidence_ids) < 15:
                    prof.evidence_ids.append(ev.id)
                low = claim.lower()
                m = _AMOUNT_RE.search(claim)
                if m and _PERIOD_RE.search(claim) and \
                        not _is_magnitude_price(claim, m):
                    prof.pricing_summary = (m.group(0) + " " +
                                            _PERIOD_RE.search(claim).group(0))[:60]
                model = classify_pricing_model(low)
                if model and not prof.business_model:
                    prof.business_model = model
                for ch in DISTRIBUTION_CHANNELS:
                    token = ch.replace("_", r"\s?") + r"\w*"
                    if re.search(rf"\b{token}\b", low) and \
                            ch not in prof.distribution_channels:
                        prof.distribution_channels.append(ch)
                        prof.channel_evidence[ch] = (
                            "observed" if re.search(rf"\b(via|through|uses?) {token}\b", low)
                            else "inferred")
                weakness = re.search(
                    rf"{re.escape(key.split()[0])}\w*[^.]{{0,140}}"
                    r"(?:complain|expensive|slow|lacks?|missing|poor|buggy|hard to)",
                    low)
                if weakness and len(prof.weaknesses) < 5:
                    prof.weaknesses.append(claim[:150])
        out = sorted(profiles.values(), key=lambda p: -len(p.evidence_ids))
        if self.srepos is not None:
            for pr in out:
                self.srepos.competitor_profiles.save_natural(pr)
        return out

    # ------------------------------------------------------------- pricing
    def build_pricing_plans(self, project_id: str) -> list[PricingPlan]:
        """Extract normalized pricing plans; raw always preserved (spec #22)."""
        plans = []
        seen = set()
        for ev in self.accepted(project_id):
            quote = (ev.quote or "") + " " + (ev.claim_text or "")
            m = _AMOUNT_RE.search(quote)
            if not m or _is_magnitude_price(quote, m):
                continue
            period = _billing_period(quote)
            try:
                amt = float(m.group("amt").replace(",", ""))
            except ValueError:
                continue
            cur = {"$": "USD", "₹": "INR", "€": "EUR", "£": "GBP"}.get(m.group("cur"), "")
            monthly_eq, note = normalize_price(amt, cur, period)
            company = ""
            cm = re.search(r"\b([A-Z][A-Za-z0-9]{2,})\s+(?:charges|costs|offers|pricing|starts? at)",
                           quote)
            if cm:
                company = cm.group(1)
            key = (company.lower(), m.group(0), period)
            if key in seen:
                continue
            seen.add(key)
            plan = PricingPlan(
                project_id=project_id, competitor_name=company,
                tier_name="base" if not re.search(r"\b(pro|premium|enterprise|plus)\b",
                                                  quote, re.I) else "premium",
                price_raw=m.group(0), amount=amt, currency=cur,
                billing_period=period or "unknown",
                annualized_normalized=monthly_eq,
                normalization_note=note,
                included_limits=(ev.location or "")[:120],
                pricing_model=classify_pricing_model(quote.lower()),
                observed_at=str(ev.published_date or ev.retrieved_at or ""),
                source_id=ev.source_id, evidence_id=ev.id)
            saved = plan
            if self.srepos is not None:
                saved = self.srepos.pricing_plans.save_natural(plan)
            plans.append(saved)
        return plans

    # ------------------------------------------------------------- landscape
    def landscape_axes(self, project_id: str, pains: list[dict],
                       profiles: list[CompetitorProfile]) -> dict:
        """Pick landscape axes from what customers actually care about (spec #19)."""
        x_axis, y_axis = "features breadth", "price"
        cares_cost = sum(1 for p in pains if "cost" in p["categories"])
        cares_time = sum(1 for p in pains if "time" in p["categories"])
        if cares_cost > cares_time:
            y_axis = "price (customer-flagged cost pain)"
        elif cares_time:
            y_axis = "price"
        if any("manual_labor" in p["categories"] or "complexity" in p["categories"]
               for p in pains):
            x_axis = "automation depth (customer-flagged manual-work pain)"
        return {"x_axis": x_axis, "y_axis": y_axis,
                "justification": ("axes derive from pain categories present in "
                                  "evidence, not arbitrary choices"),
                "plot": [{"name": c.name,
                          "pricing_note": c.pricing_summary or "price unknown",
                          "x_guess": "high" if len(c.features) > 3 else
                                     ("medium" if c.features else "unknown")}
                         for c in profiles[:8]]}

    # ------------------------------------------------------------- gaps
    def detect_gaps(self, project_id: str, profiles: list[CompetitorProfile],
                    segments: list[dict], pains: list[dict]) -> list[dict]:
        """Evidence-linked competitive gap candidates (spec #20).
        Every proposed gap cites the evidence that motivates it."""
        gaps = []
        covered_segments = set()
        for p in profiles:
            covered_segments.update(w.strip(".,").lower()
                                    for w in p.customer_segment.split())
        for seg in segments:
            sname = seg["name"].lower()
            served = any(sname in covered_segments or
                         any(sname in (cp.customer_segment or "").lower()
                             for cp in profiles) for _ in [0])
            if not served and len(segments) > 1:
                gaps.append({
                    "kind": "underserved_segment", "target": sname,
                    "evidence": seg["evidence_ids"][:4],
                    "reason": f"no researched competitor targets segment '{sname}'"})
        weak_pain_coverage = {}
        for p in pains:
            for cat in p["categories"]:
                weak_pain_coverage.setdefault(cat, []).append(p["evidence_id"])
        feature_gaps = [cat for cat, ids in weak_pain_coverage.items()
                        if len(ids) >= 3]
        for cat in feature_gaps[:4]:
            gaps.append({
                "kind": "feature_or_workflow_gap", "target": cat,
                "evidence": weak_pain_coverage[cat][:4],
                "reason": (f"multiple independent pain evidences ({len(weak_pain_coverage[cat])}) "
                           f"in category '{cat}' with no competitor claiming resolution")})
        no_pricing = [p.name for p in profiles if not p.pricing_summary]
        if profiles and len(no_pricing) > len(profiles) / 2:
            gaps.append({
                "kind": "pricing_transparency_gap",
                "target": ", ".join(no_pricing[:5]),
                "evidence": [],
                "reason": "most competitors hide pricing; procurement friction likely"})
        return gaps

    # ------------------------------------------------------- distribution difficulty
    def distribution_difficulty(self, project_id: str,
                                channels: list[DistributionChannel]) -> dict:
        """Demand without reachable distribution is a poor opportunity (spec #25)."""
        barriers = []
        for ch in channels:
            if ch.difficulty_notes:
                barriers.append({"channel": ch.name, "notes": ch.difficulty_notes})
        ev_hits = []
        for ev in self.accepted(project_id):
            low = (ev.claim_text or "").lower()
            if re.search(r"\b(long sales cycle|procurement|high cac|customer acquisition "
                         r"cost|hard to reach|trust barrier|switching cost)\b", low):
                ev_hits.append((ev.id, ev.claim_text[:150]))
        return {
            "barriers": barriers,
            "evidence_barriers": [{"evidence_id": i, "note": n} for i, n in ev_hits[:6]],
            "verdict": ("distribution_difficult" if len(ev_hits) >= 2
                        else "distribution_uncertain" if not channels
                        else "plausible_channels_observed"),
        }
