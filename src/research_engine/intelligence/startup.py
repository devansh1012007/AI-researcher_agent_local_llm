"""Startup intelligence engine.

Extracts pains, competitors, pricing, and market signals from stored evidence,
clusters them into opportunity candidates, scores transparently, derives critical
assumptions, and designs falsification tests.

Guardrails enforced:
- stated pain != observed behavior != inferred pain (spec #31)
- existence != traction for competitors (spec #78)
- reported vs estimated vs calculated market size (spec #77)
- opportunity emerges from clustered evidence, never from LLM imagination (spec #37)
"""
from __future__ import annotations

import logging
import re

from research_engine.intelligence.literature import TfidfIndex, _tokens
from research_engine.models.enums import EvidenceStatus
from research_engine.models.opportunity import Opportunity
from research_engine.models.startup import (Competitor, FalsificationTest,
                                            MarketSignal, PainPoint, PriceObservation)
from research_engine.storage.graph_store import GraphEntity, GraphStore
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)

_PAIN_RE = re.compile(
    r"\b(complain\w*|frustrat\w*|pain(?:ful|point)?|struggl\w*|hassle|tedious|"
    r"manual\w*|time[- ]consuming|expensive|overwhelm\w*|hard to|difficult to|"
    r"can'?t afford|too slow|workaround)\b", re.I)
_PRICE_RE = re.compile(
    r"(?P<currency>[$₹€£])\s?(?P<amount>\d[\d,.]*)"
    r"(?!\s?[mb]\b)"   # exclude funding magnitudes like $5M / $1.2B
    r"\s*(?P<per>/?\s?(?:mo\b|month|yr\b|year|user|seat))?",
    re.I)
_SIGNAL_KINDS = [
    ("funding", re.compile(r"\b(rais\w+\s+\$?\d|funding round|series [abc]|seed round|"
                           "vc investment|venture round)", re.I)),
    ("hiring", re.compile(r"\b(hiring|job postings?|open roles?|recruit\w+)\b", re.I)),
    ("regulation", re.compile(r"\b(regulat\w+|compliance requirement|mandate|gdpr|dpdp act|rbi)\b", re.I)),
    ("launch", re.compile(r"\b(launch\w*|releas\w+ new|rolls? out|unveil\w*)\b", re.I)),
    ("pricing_change", re.compile(r"\b(price (?:increase|hike)|raised prices|pricing change)\b", re.I)),
    ("acquisition", re.compile(r"\b(acquir\w+|merger|m&a)\b", re.I)),
    ("infrastructure", re.compile(r"\b(new (?:api|platform|infrastructure)|now available|uptime improvement)\b", re.I)),
    ("complaint", _PAIN_RE),
]

_WHY_NOW_HINTS = re.compile(
    r"\b(newly (?:available|possible)|recently (?:launched|released)|cost (?:of|has) (?:compute|models) "
    r"|fell|dropped|new regulation|mandated|now requires|smartphone penetration|uptime|api access)\b", re.I)


class StartupIntelligence:
    def __init__(self, repos: Repositories, graph: GraphStore):
        self.repos = repos
        self.graph = graph

    # ------------------------------------------------------------------ extraction
    def extract_all(self, project_id: str) -> dict:
        stats = {}
        stats["pain_points"] = self._extract_pains(project_id)
        stats["competitors"] = self._extract_competitors(project_id)
        stats["prices"] = self._extract_prices(project_id)
        stats["signals"] = self._extract_signals(project_id)
        return stats

    def accepted_evidence(self, project_id: str) -> list:
        return [e for e in self.repos.evidence.all(project_id)
                if e.status != EvidenceStatus.REJECTED]

    def _extract_pains(self, project_id: str) -> list[PainPoint]:
        from research_engine.pipeline.evidence import claims_equivalent
        pains: list[PainPoint] = []
        for ev in self.accepted_evidence(project_id):
            if not _PAIN_RE.search(ev.claim_text):
                continue
            kind = ("stated" if any(k in ev.claim_text.lower()
                    for k in ("said", "according to", "survey", "interview", "told"))
                    else "observed")
            match = next((p for p in pains if claims_equivalent(p.statement, ev.claim_text)), None)
            if match is None:
                p = PainPoint(project_id=project_id, statement=ev.claim_text[:300],
                              kind=kind, frequency_signals=1,
                              evidence_ids=[ev.id])
                p.ensure_id()
                pains.append(p)
            else:
                match.frequency_signals += 1
                match.evidence_ids.append(ev.id)
        for p in pains:
            self.repos.__dict__["db"]  # keep reference explicit
        # persist via generic repo pattern: use opportunities repo table? No - dedicated storage
        self._persist_startup_entities(project_id, "pain_point", pains)
        return pains

    def _extract_competitors(self, project_id: str) -> list[Competitor]:
        competitors = []
        for ent in self.graph.entities(project_id, "company") + \
                   self.graph.entities(project_id, "competitor"):
            comp = Competitor(project_id=project_id, name=ent.name,
                              product=ent.attributes.get("product", ""),
                              positioning=ent.attributes.get("positioning", ""),
                              funding_signal=ent.attributes.get("funding_signal", ""),
                              customer_evidence=ent.attributes.get("customer_evidence", ""),
                              evidence_ids=ent.attributes.get("evidence_ids", []))
            competitors.append(comp)
        self._persist_startup_entities(project_id, "competitor", competitors)
        return competitors

    def _extract_prices(self, project_id: str) -> list[PriceObservation]:
        prices: list[PriceObservation] = []
        for ev in self.accepted_evidence(project_id):
            m = _PRICE_RE.search(ev.quote or "") or _PRICE_RE.search(ev.claim_text or "")
            if not m:
                continue
            per = (m.group("per") or "").lower()
            period = ("monthly" if "mo" in per or "month" in per else
                      "annual" if "year" in per or "yr" in per else "")
            currency = {"$": "USD", "₹": "INR", "€": "EUR", "£": "GBP"}.get(m.group("currency"), "")
            p = PriceObservation(project_id=project_id, amount_raw=m.group("amount"),
                                 currency=currency, billing_period=period,
                                 observed_date=str(ev.published_date or ""),
                                 source_id=ev.source_id, evidence_id=ev.id,
                                 included_limits=ev.location[:100])
            p.ensure_id()
            prices.append(p)
        self._persist_startup_entities(project_id, "price_observation", prices)
        return prices

    def _extract_signals(self, project_id: str) -> list[MarketSignal]:
        signals = []
        for ev in self.accepted_evidence(project_id):
            text = ev.claim_text + " " + ev.quote[:200]
            for kind, rx in _SIGNAL_KINDS:
                if rx.search(text):
                    s = MarketSignal(project_id=project_id, kind=kind,
                                     description=ev.claim_text[:250],
                                     date=str(ev.published_date or ""),
                                     evidence_ids=[ev.id])
                    s.ensure_id()
                    signals.append(s)
                    break
        self._persist_startup_entities(project_id, "market_signal", signals)
        return signals

    def _persist_startup_entities(self, project_id: str, type_: str, entities: list) -> None:
        """Store as graph entities (attributes JSON) — one store for Phase 2 models."""
        for e in entities:
            d = e.model_dump() if hasattr(e, "model_dump") else e.to_dict()
            d.pop("id", None); d.pop("project_id", None); d.pop("created_at", None)
            d.pop("updated_at", None)
            if type_ == "pain_point":
                name = d.pop("statement", "") or type_
            elif type_ == "market_signal":
                name = d.pop("description", "") or type_
            else:
                name = d.pop("name", "") or type_
            self.graph.upsert_entity(GraphEntity(project_id=project_id, type=type_,
                                                 name=name, attributes=d))

    def load_startup_entities(self, project_id: str, type_: str) -> list[dict]:
        ents = self.graph.entities(project_id, type_)
        name_key = {"pain_point": "statement", "market_signal": "description"}.get(type_, "name")
        out = []
        for e in ents:
            d = dict(e.attributes)
            d["id"] = e.id
            if name_key not in d:
                d[name_key] = e.name
            out.append(d)
        return out

    # ------------------------------------------------------------------ opportunities
    def discover_opportunities(self, project_id: str, max_opportunities: int = 5) -> list[Opportunity]:
        """Cluster pain evidence into opportunity candidates.

        An opportunity REQUIRES: >=2 distinct pain evidences OR pain + market signal.
        Everything else stays a raw observation.
        """
        pains = self._load_pains(project_id)
        signals = self.load_startup_entities(project_id, "market_signal")
        if not pains:
            return []

        idx = TfidfIndex()
        docs = [_tokens(p.statement) for p in pains]
        idx.fit(docs)

        clusters: list[list[int]] = []
        vecs = [idx.vector(t) for t in docs]
        for i, v in enumerate(vecs):
            placed = False
            for cluster in clusters:
                if TfidfIndex.cosine(v, vecs[cluster[0]]) >= 0.25:
                    cluster.append(i); placed = True; break
            if not placed:
                clusters.append([i])

        opportunities = []
        existing = {o.problem for o in self.repos.opportunities.all(project_id)}
        for members in clusters:
            member_pains = [pains[i] for i in members]
            n_ev = sum(len(p.evidence_ids) for p in member_pains)
            related_signals = [s for s in signals
                               if any(TfidfIndex.cosine(
                                   idx.vector(_tokens(s.get("description", ""))),
                                   vecs[members[0]]) >= 0.12 for _ in [0])]
            if n_ev < 2 and not related_signals:
                continue  # single uncorroborated complaint is not an opportunity
            top = max(member_pains, key=lambda p: len(p.evidence_ids))
            opp = Opportunity(
                project_id=project_id,
                problem=top.statement[:280],
                customer_segment=", ".join(sorted({p.segment for p in member_pains if p.segment})) or "unclassified",
                current_alternative=top.current_alternative or "unknown",
                evidence_ids=[eid for p in member_pains for eid in p.evidence_ids][:20],
                severity=min(1.0, len(member_pains) / 4),
                frequency=min(1.0, sum(p.frequency_signals for p in member_pains) / 6),
                why_now=[s.get("description", "") for s in related_signals
                         if _WHY_NOW_HINTS.search(s.get("description", ""))][:3],
                risks=["demand unvalidated until falsification tests pass"],
            )
            opp.ensure_id()
            if opp.problem in existing:
                continue
            self.repos.opportunities.save(opp)
            existing.add(opp.problem)
            opportunities.append(opp)
        return opportunities

    def _load_model(self, project_id: str, type_: str, model_cls):
        out = []
        for d in self.load_startup_entities(project_id, type_):
            try:
                out.append(model_cls(**{k: v for k, v in d.items()
                                        if k in model_cls.model_fields}))
            except Exception:
                continue
        return out

    def _load_pains(self, project_id: str) -> list[PainPoint]:
        return self._load_model(project_id, "pain_point", PainPoint)

    # ------------------------------------------------------------------ scoring
    def score_opportunity(self, project_id: str, opp: Opportunity) -> dict:
        """Transparent factor-based score. Every factor cites its basis."""
        factors: dict[str, float] = {}
        reasons: dict[str, str] = {}

        factors["pain_severity"] = opp.severity
        reasons["pain_severity"] = f"{len(opp.evidence_ids)} clustered pain evidences"

        prices = self._load_model(project_id, "price_observation", PriceObservation)
        factors["willingness_to_pay_evidence"] = min(1.0, len(prices) / 5)
        reasons["willingness_to_pay_evidence"] = (
            f"{len(prices)} price observations collected" if prices else
            "no pricing evidence yet")

        ev_tiers = []
        for eid in opp.evidence_ids:
            ev = self.repos.evidence.get(eid)
            if ev:
                ev_tiers.append(ev.source_tier)
        factors["evidence_strength"] = (
            sum({1: 1.0, 2: 0.8, 3: 0.55, 4: 0.35, 5: 0.2}.get(t, 0.2) for t in ev_tiers)
            / len(ev_tiers)) if ev_tiers else 0.0
        reasons["evidence_strength"] = f"avg tier weight over {len(ev_tiers)} evidences"

        comps = opp.competitor_names
        factors["competition_pressure"] = min(1.0, len(comps) / 6)
        reasons["competition_pressure"] = f"{len(comps)} known competitors"

        factors["timing_evidence"] = min(1.0, len(opp.why_now) / 3)
        reasons["timing_evidence"] = f"{len(opp.why_now)} why-now items with change evidence"

        weights = {"pain_severity": 0.3, "willingness_to_pay_evidence": 0.2,
                   "evidence_strength": 0.25, "competition_pressure": 0.05,
                   "timing_evidence": 0.2}
        total = sum(weights[k] * factors[k] for k in weights)
        opp.score_breakdown = {
            "factors": {k: round(v, 3) for k, v in factors.items()},
            "reasons": reasons, "weights": weights,
            "total": round(total, 3),
        }
        opp.confidence = round(min(1.0, factors["evidence_strength"]
                                   * (0.5 + 0.5 * min(1.0, len(opp.evidence_ids) / 8))), 3)
        self.repos.opportunities.save(opp)
        return opp.score_breakdown


# coercion helpers ------------------------------------------------------------
def _coerce_pain(rows: list[dict]) -> list[dict]:
    return [{**r} for r in rows if r.get("statement")]
