"""Signal analyzer: timestamped market signals with independence tracking,
strength grading, technology-shift detection and WHY-NOW assembly.

Discipline:
- Ten articles repeating one announcement == ONE underlying signal (spec #29):
  signals sharing the same underlying event (near-identical claim or same
  primary domain) are merged.
- Strength grades (STRONG/MEDIUM/WEAK/UNKNOWN) always carry a reason; no
  invented probabilities (spec #30).
- No credible why-now evidence => explicit WHY_NOW_WEAK marker (spec #27).
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from research_engine.intelligence.literature import TfidfIndex, _tokens
from research_engine.specialists.startup.models import TechnologyShift
from research_engine.storage.repositories import Repositories

_TECH_SHIFT_RE = re.compile(
    r"\b(new (?:model|ai|llm|api|platform)|now (?:available|possible|supports?)|"
    r"open[- ]sourc\w+|cost of (?:compute|inference|storage) (?:fell|dropped|declined)|"
    r"price of \w+ (?:fell|dropped)|new regulation|mandated|uPI|smartphone penetration)\b", re.I)


class SignalAnalyzer:
    def __init__(self, repos: Repositories, graph=None, provider=None, srepos=None):
        self.repos = repos
        self.graph = graph
        self.provider = provider
        self.srepos = srepos

    def accepted(self, project_id: str) -> list:
        return [e for e in self.repos.evidence.all(project_id)
                if e.status != "REJECTED"]

    def _domain_of(self, ev) -> str:
        url = getattr(ev, "source_url", "") or ""
        try:
            return urlparse(url).netloc.lower()
        except ValueError:
            return ""

    # ------------------------------------------------------------- signals
    def collect_signals(self, project_id: str,
                        base_signals: list[dict] | None = None) -> list[dict]:
        """Merge raw signal mentions into independent underlying signals.

        `base_signals` are dicts from the Phase-2 extractor (kind/description/
        date/evidence_ids). Two mentions merge when their descriptions are
        near-duplicates OR they share a primary source domain.
        """
        raw = list(base_signals or [])
        for ev in self.accepted(project_id):
            text = ev.claim_text or ""
            if not re.search(r"\b(rais\w+ \$?\d|funding round|series [abc]|acquisition|"
                             r"launch\w*|regulat\w+|price (?:increase|hike)|hiring)\b",
                             text, re.I):
                continue
            raw.append({"kind": "funding" if re.search(r"funding|rais\w+|series", text, re.I)
                        else "regulation" if re.search(r"regulat", text, re.I)
                        else "launch" if re.search(r"launch", text, re.I)
                        else "pricing_change" if re.search(r"price", text, re.I)
                        else "other",
                        "description": text[:250],
                        "date": str(ev.published_date or ""),
                        "evidence_ids": [ev.id],
                        "_domain": self._domain_of(ev)})
        # cluster near-duplicates (spec #29)
        idx = TfidfIndex()
        docs = [_tokens(r["description"]) for r in raw]
        idx.fit(docs)
        clusters: list[list[int]] = []
        vecs = [idx.vector(t) for t in docs]
        for i, v in enumerate(vecs):
            placed = False
            for cl in clusters:
                rep = cl[0]
                sim = TfidfIndex.cosine(v, vecs[rep])
                same_domain = (raw[i].get("_domain") and
                               raw[i]["_domain"] == raw[rep].get("_domain"))
                if sim >= 0.5 or (same_domain and sim >= 0.3):
                    cl.append(i)
                    placed = True
                    break
            if not placed:
                clusters.append([i])

        out = []
        for cl in clusters:
            members = [raw[i] for i in cl]
            merged_ev = sorted({eid for m in members for eid in m.get("evidence_ids", [])})
            domains = {m["_domain"] for m in members if m.get("_domain")}
            n_underlying = len(domains) if domains else len(cl)
            sig = {
                "kind": members[0]["kind"],
                "description": max((m["description"] for m in members),
                                   key=len)[:280],
                "date": max(m.get("date", "") for m in members),
                "evidence_ids": merged_ev[:10],
                "mentions": len(members),
                "underlying_sources": n_underlying,
                "domains": sorted(domains)[:6],
            }
            sig.update(self._grade(sig))
            out.append(sig)
        out.sort(key=lambda s: -s["strength_score"])
        return out

    @staticmethod
    def _grade(sig: dict) -> dict:
        """STRONG/MEDIUM/WEAK/UNKNOWN with an explicit reason (spec #30)."""
        n_sources = sig.get("underlying_sources", 1)
        kind = sig.get("kind", "")
        dated = bool(sig.get("date"))
        if n_sources >= 2 and kind in ("funding", "regulation", "acquisition") and dated:
            grade, score = "STRONG", 0.9
            reason = f"{n_sources} independent sources, dated, verifiable kind '{kind}'"
        elif n_sources >= 2:
            grade, score = "MEDIUM", 0.6
            reason = f"{n_sources} distinct sources but weaker kind '{kind}'"
        elif dated:
            grade, score = "MEDIUM", 0.5
            reason = "single dated source"
        elif n_sources >= 1:
            grade, score = "WEAK", 0.3
            reason = "single undated source"
        else:
            grade, score = "UNKNOWN", 0.1
            reason = "no attributable source"
        return {"strength": grade, "strength_score": score, "strength_reason": reason}

    # ------------------------------------------------------------- tech shifts
    def detect_tech_shifts(self, project_id: str) -> list[TechnologyShift]:
        shifts = []
        seen = set()
        existing_fp = set()
        if self.srepos is not None:
            from research_engine.specialists.startup.identity import desc_fingerprint as _df
            existing_fp = {_df(t.description) for t in self.srepos.tech_shifts.all(project_id)}
        for ev in self.accepted(project_id):
            text = (ev.claim_text or "")
            if not _TECH_SHIFT_RE.search(text):
                continue
            key = text[:60].lower()
            fp = None
            from research_engine.specialists.startup.identity import desc_fingerprint as _df
            fp = _df(text)
            if key in seen or fp in existing_fp:
                continue
            seen.add(key)
            existing_fp.add(fp)
            low = text.lower()
            kind = ("regulatory_change" if "regulation" in low or "mandate" in low
                    else "cost_reduction" if re.search(r"cost|price.*(fell|dropped)", low)
                    else "open_source" if "open-sourc" in low
                    else "api_availability" if "api" in low
                    else "model_capability")
            t = TechnologyShift(
                project_id=project_id, kind=kind, description=text[:250],
                enables=re.sub(r"^.*\b(?:now|enables?|allows?)\b", "", text,
                               flags=re.I).strip()[:160] or "see description",
                date_observed=str(ev.published_date or ""),
                evidence_ids=[ev.id])
            t.ensure_id()
            shifts.append(t)
            if self.srepos is not None:
                self.srepos.tech_shifts.save(t)   # fingerprint pre-deduped above
        return shifts

    # ------------------------------------------------------------- why now
    def build_why_now(self, project_id: str, opportunity_problem: str,
                      signals: list[dict], shifts: list[TechnologyShift]) -> dict:
        """Assemble why-now items WITH change evidence; WHY_NOW_WEAK when absent."""
        from research_engine.intelligence.literature import TfidfIndex as TI
        prob_vec = None
        idx = TI()
        idx.fit([_tokens(opportunity_problem)])
        prob_vec = idx.vector(_tokens(opportunity_problem))

        items = []
        for s in signals:
            sim = TI.cosine(prob_vec, idx.vector(_tokens(s["description"])))
            if sim >= 0.08:
                items.append({"source": "market_signal", "text": s["description"][:200],
                              "date": s.get("date", ""), "strength": s["strength"],
                              "relevance": round(sim, 2)})
        for t in shifts:
            sim = TI.cosine(prob_vec, idx.vector(_tokens(t.description)))
            if sim >= 0.05:
                items.append({"source": "technology_shift", "text": t.description[:200],
                              "date": t.date_observed, "kind": t.kind,
                              "relevance": round(sim, 2)})
        items.sort(key=lambda i: -i.get("relevance", 0))
        strong = [i for i in items
                  if i["source"] == "technology_shift" or i.get("strength") in ("STRONG", "MEDIUM")]
        verdict = ("supported" if strong else "WHY_NOW_WEAK")
        return {"verdict": verdict,
                "items": items[:5],
                "note": ("why-now items cite specific change evidence" if strong else
                         "no credible change evidence found — timing remains "
                         "unproven and must be marked WHY_NOW_WEAK")}
