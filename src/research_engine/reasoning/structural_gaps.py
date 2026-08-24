"""Structural gap detectors - deterministic, evidence-based.

These run alongside the LLM gap analyzer and guarantee detection of structural
weaknesses even with weak/no local models:

- SOURCE_DIVERSITY_GAP: one domain dominates evidence (spec #122)
- NEGATIVE_EVIDENCE_GAP: nearly all evidence is supportive/positive
- INDEPENDENT_REPLICATION_GAP: important claims lack independent corroboration
- BASELINE/BENCHMARK/METHOD_COMPARISON gaps (academic)
- VALIDATION/CUSTOMER_SEGMENT/COMPETITOR/GEOGRAPHIC gaps (startup)
- CAUSALITY_GAP: correlational language without causal support
"""
from __future__ import annotations

import re

from research_engine.models.analysis import Gap
from research_engine.models.enums import EvidenceStatus, GapCategory, Severity
from research_engine.storage.repositories import Repositories

_POSITIVE = re.compile(
    r"\b(improv|outperform|superior|effective|succeed|gain|growth|adopt|promis|strong)\w*", re.I)
_NEGATIVE = re.compile(
    r"\b(fail|limitation|weakness|degrad|underperform|worse|criticism|concern|"
    r"complain|problem|drawback|shortcoming|flaw)\w*", re.I)
_CORRELATION = re.compile(r"\b(correlat\w*|associat\w*|linked to|tied to)\b", re.I)
_CAUSAL = re.compile(r"\b(cause[ds]?|causes|because of|due to|leads? to|results? in)\b", re.I)


class StructuralGapDetector:
    def __init__(self, repos: Repositories):
        self.repos = repos

    def detect(self, project_id: str, mode: str) -> list[Gap]:
        ev = [e for e in self.repos.evidence.all(project_id)
              if e.status != EvidenceStatus.REJECTED]
        if not ev:
            return []
        out: list[Gap] = []

        # --- source diversity pressure -------------------------------------
        domains = {}
        for e in ev:
            dom = e.source_url.split("/")[0] if "/" in e.source_url else e.source_url
            domains[dom] = domains.get(dom, 0) + 1
        top_dom, n_top = max(domains.items(), key=lambda kv: kv[1])
        share = n_top / len(ev)
        if len(domains) < 3 or share >= 0.6:
            out.append(Gap(
                description=f"{share:.0%} of accepted evidence comes from '{top_dom}' "
                            f"({len(domains)} domain(s) total); independent-domain "
                            "confirmation is missing.",
                category=GapCategory.SOURCE_DIVERSITY_GAP,
                importance=0.75 if share >= 0.8 else 0.55,
                severity=Severity.HIGH if share >= 0.8 else Severity.MEDIUM,
                evidence_needed="Evidence from additional independent organizations/domains."))

        # --- negative evidence balance (spec #120/#122) ----------------------
        pos = sum(1 for e in ev if _POSITIVE.search(e.claim_text))
        neg = sum(1 for e in ev if _NEGATIVE.search(e.claim_text))
        if len(ev) >= 5 and neg / max(1, pos + neg) < 0.15:
            out.append(Gap(
                description=f"Evidence balance skews positive ({pos} supportive vs {neg} "
                            "critical items); counter-evidence and failure cases are "
                            "under-collected.",
                category=GapCategory.NEGATIVE_EVIDENCE_GAP,
                importance=0.7, severity=Severity.MEDIUM,
                evidence_needed="Failure analyses, criticism, negative results, complaints."))

        # --- independence / replication for important claims -----------------
        claims = [c for c in self.repos.claims.all(project_id)
                  if c.confidence >= 0.5 and c.supported_by]
        ev_by_id = {e.id: e for e in ev}
        unreplicated = [c for c in claims
                        if len({ev_by_id[e].source_id for e in c.supported_by
                                if e in ev_by_id}) < 2]
        if claims and len(unreplicated) / len(claims) >= 0.7:
            out.append(Gap(
                description=f"{len(unreplicated)}/{len(claims)} material claims have no "
                            "second independent source; replication evidence missing.",
                category=GapCategory.INDEPENDENT_REPLICATION_GAP,
                importance=0.7, severity=Severity.MEDIUM,
                evidence_needed="Independent confirmation from a different organization."))

        # --- causality guardrail ---------------------------------------------
        correlational = [e for e in ev if _CORRELATION.search(e.claim_text)]
        causal_overreach = [e for e in correlational
                            if _CAUSAL.search(e.claim_text)]
        if causal_overreach:
            out.append(Gap(
                description=f"{len(causal_overreach)} evidence items mix correlational "
                            "and causal language; causal interpretation is unsupported.",
                category=GapCategory.CAUSALITY_GAP,
                importance=0.65, severity=Severity.MEDIUM,
                evidence_needed="Experimental/interventional evidence or explicit causal identification."))

        # --- academic structural gaps -----------------------------------------
        if mode == "academic":
            benchmarks = [e for e in ev
                          if any("benchmark" in t.lower() or "dataset" in t.lower()
                                 for t in e.tags)]
            comparisons = [e for e in ev
                           if any(k in e.claim_text.lower()
                                  for k in ("compared", "comparison", "versus", " vs ",
                                            "baseline", "against"))]
            if len(ev) >= 8 and len(comparisons) < len(ev) * 0.1:
                out.append(Gap(
                    description="Methods are described but head-to-head comparisons / "
                                "baseline evaluations are largely absent.",
                    category=GapCategory.METHOD_COMPARISON_GAP,
                    importance=0.7, severity=Severity.MEDIUM,
                    evidence_needed="Papers comparing methods on shared benchmarks."))
            if not benchmarks and len(ev) >= 8:
                out.append(Gap(
                    description="No benchmark/dataset usage identified across the "
                                "collected literature.",
                    category=GapCategory.BENCHMARK_GAP,
                    importance=0.6, severity=Severity.LOW,
                    evidence_needed="Which benchmarks/datasets the field evaluates on."))

        # --- startup structural gaps -------------------------------------------
        if mode == "startup":
            pricing = [e for e in ev
                       if any(k in (e.claim_text + " " + " ".join(e.tags)).lower()
                              for k in ("pricing", "price", "$", "/mo", "per month",
                                        "cost"))]
            customer_ev = [e for e in ev
                           if any(k in (e.claim_text + " " + " ".join(e.entities)).lower()
                                  for k in ("customer", "user", "business", "clinic",
                                            "retailer", "shop", "merchant", "owner"))]
            if pricing:
                geos = set()
                for e in pricing:
                    m = None
                    geo_terms = ("india", "global", "us ", "usa", "europe", "uk")
                    text = (e.claim_text + " " + e.source_title).lower()
                    geos.update(g.strip() for g in geo_terms if g in text)
                if len(pricing) >= 3 and len(geos) <= 1:
                    out.append(Gap(
                        description="Pricing evidence lacks geographic spread; market-"
                                    "specific pricing cannot be inferred.",
                        category=GapCategory.GEOGRAPHIC_GAP,
                        importance=0.5, severity=Severity.LOW,
                        evidence_needed="Region-specific pricing/market numbers."))
            if customer_ev and not self._segment_coverage(customer_ev):
                out.append(Gap(
                    description="Customer-level evidence exists but segments are not "
                                "distinguished; segment-specific pain unknown.",
                    category=GapCategory.CUSTOMER_SEGMENT_GAP,
                    importance=0.6, severity=Severity.MEDIUM,
                    evidence_needed="Evidence attributed to specific customer segments."))

        for g in out:
            g.project_id = project_id
        return out

    @staticmethod
    def _segment_coverage(customer_ev) -> bool:
        seg_markers = sum(1 for e in customer_ev
                          if any(s in (e.claim_text).lower() for s in
                                 ("segment", "smb", "enterprise", "retail", "clinic",
                                  "manufacturer", "school")))
        return seg_markers >= max(2, len(customer_ev) // 3)
