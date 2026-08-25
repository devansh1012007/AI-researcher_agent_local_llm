"""Market analyzer: definition-first market modeling with size cross-validation.

Discipline enforced here:
- Market DEFINITION precedes market SIZING (spec #7): ambiguous definitions
  become research gaps, never silent assumptions.
- Every size figure keeps value/currency/year/geography/method/source (spec #8).
- Conflicting size figures are NEVER averaged (spec #9); conflicts stay
  visible as MARKET_SIZE_CONFLICT contradictions.

LLM is optional: every function has a deterministic fallback so the engine
works fully offline (mock provider / no model).
"""
from __future__ import annotations

import logging
import re

from research_engine.models.analysis import Gap
from research_engine.models.enums import GapCategory, Severity
from research_engine.specialists.startup.models import Market, MarketSizeEstimate
from research_engine.specialists.startup.policies import route_question_kind
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)

_NUM_RE = re.compile(r"(?P<cur>[$₹€£])?\s?(?P<val>\d[\d,]*(?:\.\d+)?)\s?"
                     r"(?P<mag>(?:trillion|billion|million|bn|mn|mm|b|m|k|cr|lakh))?\b", re.I)
_MAG = {"trillion": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9,
        "million": 1e6, "mn": 1e6, "mm": 1e6, "m": 1e6,
        "k": 1e3, "cr": 1e7, "lakh": 1e5}
_CURRENCY = {"$": "USD", "₹": "INR", "€": "EUR", "£": "GBP"}

# definition dimensions required before sizing (spec #7)
_DEFINITION_DIMENSIONS = {
    "what_is_sold": re.compile(r"\b(software|platform|service|product|tool|solution)s?\b", re.I),
    "customer": re.compile(r"\b(smb|enterprise|businesses|consumers?|startups|retail\w*|clinics)\b", re.I),
    "use_case": re.compile(r"\b(for|to manage|to automate|used for|workflow)\b", re.I),
    "geography": re.compile(r"\b(india|global|usa|us\b|europe|eu\b|apac|southeast asia|africa)\b", re.I),
}


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s[:80] or "unnamed-market"


class MarketAnalyzer:
    def __init__(self, repos: Repositories, provider=None, srepos=None):
        self.repos = repos
        self.provider = provider  # optional LLM (router.reasoning)
        self.srepos = srepos      # optional StartupRepos for domain persistence

    # ------------------------------------------------------------- definition
    def build_market(self, project_id: str, question: str) -> Market:
        """Build the market entity from the research question + evidence.
        Missing definition dimensions become visible gaps (spec #7)."""
        evs = [e for e in self.repos.evidence.all(project_id)
               if e.status != "REJECTED"]
        mkt = Market(project_id=project_id, name=question.strip()[:120],
                     market_slug=slugify(question))
        text_corpus = question + "\n" + "\n".join(e.claim_text for e in evs[:80])

        for dim, rx in _DEFINITION_DIMENSIONS.items():
            if not rx.search(text_corpus):
                mkt.definition_gaps.append(dim)
        mkt.geography = self._first_match(text_corpus, _DEFINITION_DIMENSIONS["geography"])
        if mkt.definition_gaps:
            gap = Gap(project_id=project_id,
                      description=("Market definition incomplete — unresolved "
                                   f"dimensions: {', '.join(mkt.definition_gaps)}. "
                                   "Market sizing must not proceed on an undefined market."),
                      category=GapCategory.CUSTOMER_SEGMENT_GAP,
                      importance=0.8, severity=Severity.HIGH,
                      evidence_needed="definition clarifications from primary sources",
                      recommended_queries=[],
                      iteration_found=0)
            gap.ensure_id()
            existing = {g.description[:60] for g in self.repos.gaps.all(project_id)}
            if gap.description[:60] not in existing:
                self.repos.gaps.save(gap)
        mkt.ensure_id()
        return mkt

    @staticmethod
    def _first_match(text: str, rx: re.Pattern) -> str:
        m = rx.search(text or "")
        return m.group(0) if m else ""

    # ------------------------------------------------------------- sizing
    def collect_sizes(self, project_id: str, market: Market) -> list[MarketSizeEstimate]:
        """Extract attributed MARKET-SIZE estimates from numeric evidence.

        P0-07 fix: the statement is CLASSIFIED first (canonical policies);
        only genuine market-size statements yield estimates. Funding,
        revenue, valuations, years and growth rates are never misattributed."""
        from research_engine.specialists.startup.policies import (
            classify_numeric_statement, parse_money)
        out = []
        seen_evidence = set()
        for ev in self.repos.evidence.all(project_id):
            if ev.status == "REJECTED" or ev.id in seen_evidence:
                continue
            claim = ev.claim_text or ""
            kind = classify_numeric_statement(claim)
            if kind != "market_size":
                continue
            value, currency, _mag = parse_money(claim)
            raw_snippet = self._size_snippet(claim)
            est = MarketSizeEstimate(
                project_id=project_id, market_id=market.id,
                value_raw=raw_snippet,
                value=value,
                currency=currency or self._currency_of(claim),
                year=self._year_of(claim),
                geography=(self._first_match(claim, _DEFINITION_DIMENSIONS["geography"])
                           or market.geography or "unspecified"),
                method=self._method_of(claim),
                definition_note=claim[:200],
                source_id=ev.source_id, evidence_id=ev.id,
                confidence=min(0.9, 0.3 + 0.15 * max(0, 4 - ev.source_tier)))
            est.ensure_id()
            seen_evidence.add(ev.id)
            out.append(est)
            if self.srepos is not None:
                self.srepos.market_sizes.save_natural(est)
        return out

    @staticmethod
    def _size_snippet(claim: str) -> str:
        m = _NUM_RE.search(claim)
        if not m:
            return claim[:80]
        start = max(0, m.start() - 40)
        return claim[start:m.end() + 20].strip()

    @staticmethod
    def _parse_value(claim: str) -> float:
        m = _NUM_RE.search(claim)
        if not m:
            return 0.0
        try:
            val = float(m.group("val").replace(",", ""))
        except ValueError:
            return 0.0
        mag = m.group("mag")
        return val * _MAG.get(mag.lower(), 1.0) if mag else val

    @staticmethod
    def _currency_of(claim: str) -> str:
        m = re.search(r"[$₹€£]", claim)
        return _CURRENCY.get(m.group(0), "") if m else ""

    @staticmethod
    def _year_of(claim: str) -> str:
        years = re.findall(r"\b(20\d{2})\b", claim)
        return years[-1] if years else ""

    @staticmethod
    def _method_of(claim: str) -> str:
        c = claim.lower()
        if "tam" in c:
            return "TAM"
        if "sam" in c:
            return "SAM"
        if "som" in c:
            return "SOM"
        if "bottom-up" in c or "bottom up" in c:
            return "bottom_up"
        if "top-down" in c or "top down" in c:
            return "top_down"
        return "reported"

    # ------------------------------------------------------- cross-validation
    def cross_validate_sizes(self, project_id: str, market: Market,
                             sizes: list[MarketSizeEstimate],
                             conflict_ratio: float = 1.5) -> dict:
        """Group comparable figures; flag conflicts; NEVER average (spec #9).

        Figures are comparable only when currency AND geography AND method-class
        agree. Different years/geographies/methods are differences to EXPLAIN,
        not numbers to blend.
        """
        report: dict = {"comparable_groups": [], "conflicts": [], "excluded": []}

        def norm_bucket(s: MarketSizeEstimate) -> tuple:
            """Comparability key = (currency, geography, method-class).

            UNSPECIFIED geography normalizes to '' and is treated as a
            WILDCARD during grouping (see merge_wildcards): an unattributed
            figure must not silently escape cross-validation merely because
            its source omitted a location."""
            method_class = "modeled" if s.method in ("bottom_up", "top_down") else \
                ("funnel" if s.method in ("TAM", "SAM", "SOM") else "reported")
            geo = "" if s.geography.lower() in ("", "unspecified") \
                else s.geography.lower()
            return (s.currency, geo, method_class)

        def merge_wildcards(groups: dict[tuple, list]) -> dict[tuple, list]:
            """Fold unspecified-geo rows into their single attributed twin.

            Ambiguity (multiple attributed hosts for the same
            currency+method-class) keeps wildcard rows in their own group —
            we never guess a location just to force a comparison."""
            merged: dict[tuple, list] = {}
            for key, rows in groups.items():
                if key[1] != "":
                    merged.setdefault(key, []).extend(rows)
            wildcards = sorted((k, v) for k, v in groups.items() if k[1] == "")
            for (cur, _geo, mc), rows in wildcards:
                hosts = [k for k in merged if k[0] == cur and k[2] == mc]
                if len(hosts) == 1:
                    merged[hosts[0]] = merged[hosts[0]] + rows
                else:
                    merged.setdefault((cur, "", mc), []).extend(rows)
            return merged

        buckets: dict[tuple, list[MarketSizeEstimate]] = {}
        for s in sizes:
            if s.value <= 0:
                report["excluded"].append({"id": s.id,
                                           "reason": "unparseable value",
                                           "raw": s.value_raw})
                continue
            buckets.setdefault(norm_bucket(s), []).append(s)
        buckets = merge_wildcards(buckets)

        conflicts = []
        for key, group in buckets.items():
            if len(group) < 2:
                continue
            values = sorted(g.value for g in group)
            spread = values[-1] / values[0] if values[0] > 0 else 1.0
            entry = {
                "bucket": {"currency": key[0], "geography": key[1],
                           "method_class": key[2]},
                "values": [{"id": g.id, "value": g.value, "year": g.year,
                            "source_id": g.source_id, "raw": g.value_raw}
                           for g in group],
                "spread_ratio": round(spread, 2),
            }
            report["comparable_groups"].append(entry)
            if spread > conflict_ratio:
                entry["verdict"] = "MARKET_SIZE_CONFLICT"
                conflicts.append(entry)
                # keep the conflict visible as a contradiction row + flag
                con_text = ("Market size figures disagree beyond tolerance "
                            f"(spread {round(spread, 2)}x for {key}): "
                            + "; ".join(f"{g.value_raw} ({g.year or 'n/y'})" for g in group)
                            + ". Definitions, years, geographies or methodology may differ. "
                              "NOT averaged — investigate before use.")
                from research_engine.models.analysis import Contradiction
                ev_ids = sorted({g.evidence_id for g in group if g.evidence_id})
                con = Contradiction(project_id=project_id,
                                    statement_a=group[0].value_raw,
                                    statement_b=group[-1].value_raw,
                                    explanation=con_text[:400],
                                    source_quality_note=(
                                        "figures may measure different market definitions"),
                                    follow_up_query=(f"{market.name} market size definition "
                                                     "methodology comparison"),
                                    conflict_type="NUMERICAL",
                                    evidence_a_ids=[group[0].evidence_id],
                                    evidence_b_ids=[group[-1].evidence_id] if len(group) > 1 else [],
                                    )
                con.ensure_id()
                known = {c.explanation[:80] for c in
                         self.repos.contradictions.all(project_id)}
                if con_text[:80] not in known:
                    self.repos.contradictions.save(con)
                for g in group:
                    g.conflict_flag = "MARKET_SIZE_CONFLICT"
                    if self.srepos is not None:
                        self.srepos.market_sizes.save_natural(g, merge=False)
        report["conflicts"] = conflicts
        report["resolved_consensus"] = (
            len(conflicts) == 0 and len(report["comparable_groups"]) > 0)
        return report
