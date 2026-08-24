"""Literature intelligence: mapping, clustering, comparisons, trends.

Built directly on stored evidence/sources. Pure-Python TF-IDF + greedy
agglomerative clustering - no heavyweight dependencies, deterministic.
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from research_engine.models.enums import SourceType
from research_engine.storage.graph_store import GraphStore
from research_engine.storage.repositories import Repositories

log = logging.getLogger(__name__)

_STOP = set("""a an and are as at be by for from has have in is it its of on or that the
this to was were will with within we our their these those using based paper propose
present show results method approach model data dataset study research""".split())


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower())
            if len(t) > 2 and t not in _STOP]


# ---------------------------------------------------------------------------
# Lightweight TF-IDF vectorizer + greedy agglomerative clustering
# ---------------------------------------------------------------------------

class TfidfIndex:
    def __init__(self):
        self.df: Counter = Counter()
        self.n_docs = 0

    def fit(self, docs: list[list[str]]) -> None:
        self.n_docs = len(docs)
        for d in docs:
            self.df.update(set(d))

    def vector(self, tokens: list[str]) -> dict[str, float]:
        tf = Counter(tokens)
        vec = {}
        for t, n in tf.items():
            idf = math.log((1 + self.n_docs) / (1 + self.df.get(t, 0))) + 1.0
            vec[t] = (1 + math.log(n)) * idf
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    @staticmethod
    def cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if len(a) > len(b):
            a, b = b, a
        return sum(v * b.get(t, 0.0) for t, v in a.items())


@dataclass
class PaperCluster:
    cluster_id: int
    label: str
    papers: list = field(default_factory=list)     # source entities
    top_terms: list[str] = field(default_factory=list)


def cluster_papers(papers: list[dict], threshold: float = 0.18,
                   max_clusters: int = 12) -> list[PaperCluster]:
    """Greedy agglomerative clustering over title+abstract TF-IDF."""
    if not papers:
        return []
    texts = [(p.get("title", "") + " " + p.get("abstract", "")) for p in papers]
    toks = [_tokens(t) for t in texts]
    idx = TfidfIndex()
    idx.fit(toks)
    vecs = [idx.vector(t) for t in toks]

    clusters: list[list[int]] = []
    for i, v in enumerate(vecs):
        best_j, best_sim = -1, 0.0
        for ci, members in enumerate(clusters):
            sim = max(TfidfIndex.cosine(v, vecs[m]) for m in members)
            if sim > best_sim:
                best_sim, best_j = sim, ci
        if best_sim >= threshold and best_j >= 0:
            clusters[best_j].append(i)
        else:
            clusters.append([i])
    clusters.sort(key=len, reverse=True)
    clusters = clusters[:max_clusters]

    out = []
    for cid, members in enumerate(clusters):
        term_counter: Counter = Counter()
        for m in members:
            term_counter.update(toks[m])
        top_terms = [t for t, _ in term_counter.most_common(6)]
        label = ", ".join(top_terms[:3]).title()
        out.append(PaperCluster(cluster_id=cid, label=label,
                                papers=[papers[m] for m in members],
                                top_terms=top_terms))
    return out


# ---------------------------------------------------------------------------
# Foundational / recent detection
# ---------------------------------------------------------------------------

def detect_foundational(papers: list[dict], top_n: int = 5) -> list[dict]:
    """Composite score; citations matter but never alone (spec #22)."""
    now_year = datetime.now(timezone.utc).year
    scored = []
    max_cit = max((p.get("citations") or 0) for p in papers) or 1
    for p in papers:
        year = p.get("year") or _year_of(p.get("published"))
        if not year:
            continue
        age = max(0, now_year - year)
        cit_norm = (p.get("citations") or 0) / max_cit
        age_factor = min(1.0, age / 8)              # older => more foundational potential
        centrality = min(1.0, len(_tokens(p.get("title", "") + " " + p.get("abstract", ""))) / 120)
        score = 0.5 * cit_norm + 0.3 * age_factor + 0.2 * centrality
        scored.append({**p, "foundational_score": round(score, 3)})
    scored.sort(key=lambda x: -x["foundational_score"])
    return scored[:top_n]


def detect_recent_relevant(papers: list[dict], current_year: int | None = None,
                           window: int = 2, top_n: int = 5) -> list[dict]:
    now_year = current_year or datetime.now(timezone.utc).year
    scored = []
    for p in papers:
        year = p.get("year") or _year_of(p.get("published"))
        if not year or now_year - year > window:
            continue
        momentum = min(1.0, (p.get("citations") or 0) / 50)
        recency = 1.0 - (now_year - year) / (window + 1)
        score = 0.5 * recency + 0.3 * momentum + 0.2 * min(
            1.0, len(_tokens(p.get("title", ""))) / 40)
        scored.append({**p, "recent_score": round(score, 3)})
    scored.sort(key=lambda x: -x["recent_score"])
    return scored[:top_n]


def _year_of(date_str) -> int | None:
    try:
        return int(str(date_str)[:4])
    except (ValueError, TypeError):
        return None


def publication_trend(papers: list[dict]) -> dict[int, int]:
    counts: dict[int, int] = defaultdict(int)
    for p in papers:
        y = p.get("year") or _year_of(p.get("published"))
        if y:
            counts[y] += 1
    return dict(sorted(counts.items()))


def trend_observation(trend: dict[int, int]) -> str:
    """Evidence-supported trend statement; no fortune-telling (spec #26)."""
    years = sorted(y for y in trend if y >= datetime.now(timezone.utc).year - 5)
    if len(years) < 2:
        return "Insufficient dated publications to characterize a volume trend."
    recent, prior = years[-1], years[-2]
    delta = trend[recent] - trend[prior]
    direction = ("increased" if delta > 0 else "decreased" if delta < 0 else "held steady")
    return (f"Publication volume in the collected literature {direction} "
            f"from {trend[prior]} ({prior}) to {trend[recent]} ({recent}) — observed in "
            f"{sum(trend.values())} collected papers only; not a field-wide estimate.")


# ---------------------------------------------------------------------------
# Method & benchmark intelligence
# ---------------------------------------------------------------------------

def extract_benchmark_results(repos: Repositories, project_id: str) -> list[dict]:
    """BenchmarkResult rows derived from evidence tagged/mentioning benchmarks.

    Every result preserves its evaluation setting so metrics are NEVER compared
    across incompatible setups (spec #24).
    """
    results = []
    sources = {s.id: s for s in repos.sources.all(project_id)}
    for ev in repos.evidence.all(project_id):
        if ev.status.value == "REJECTED":
            continue
        tags_l = " ".join(ev.tags).lower()
        text = ev.claim_text.lower()
        bench = next((t for t in ev.tags
                      if any(k in t.lower() for k in ("benchmark", "dataset", "corpus"))), "")
        metric = ""
        m = re.search(r"\b(accuracy|success rate|success|f1|bleu|em|pass@k|win rate)\b",
                      text + " " + tags_l)
        if m:
            metric = m.group(1)
        num = ev.numbers[0].value_raw if ev.numbers else ""
        if not (bench or metric):
            continue
        src = sources.get(ev.source_id)
        results.append({
            "evidence_id": ev.id, "paper": src.title if src else "",
            "benchmark": bench, "metric": metric, "value": num,
            "setting": ev.location, "date": ev.published_date,
            "claim": ev.claim_text[:160],
        })
    return results


def compare_methods(method_evidence: dict[str, list[dict]]) -> list[dict]:
    """Structured method comparison preserving experimental settings.

    method_evidence: {"Method A": [{claim, benchmark, metric, value, date}...], ...}
    Returns comparison rows; flags incomparable settings instead of comparing blindly.
    """
    methods = list(method_evidence.keys())
    rows = []
    for i, a in enumerate(methods):
        for b in methods[i + 1:]:
            shared_settings = _shared_setting(method_evidence[a], method_evidence[b])
            rows.append({
                "method_a": a, "method_b": b,
                "comparable_on_shared_benchmarks": bool(shared_settings),
                "shared_settings": shared_settings,
                "note": ("compare only on shared benchmarks/settings"
                         if shared_settings else
                         "no shared evaluation setting found; direct metric comparison INVALID"),
                "strengths_a": [d["claim"] for d in method_evidence[a][:3]],
                "strengths_b": [d["claim"] for d in method_evidence[b][:3]],
            })
    return rows


def _shared_setting(evs_a: list[dict], evs_b: list[dict]) -> list[str]:
    sa = {(d.get("benchmark"), d.get("metric")) for d in evs_a}
    sb = {(d.get("benchmark"), d.get("metric")) for d in evs_b}
    return sorted({f"{b}/{m}" for b, m in (sa & sb) if b or m})


# ---------------------------------------------------------------------------
# Literature mapper facade
# ---------------------------------------------------------------------------

class LiteratureMapper:
    """Builds the literature map from project state."""

    def __init__(self, repos: Repositories, graph: GraphStore | None = None):
        self.repos = repos
        self.graph = graph

    def collect_papers(self, project_id: str) -> list[dict]:
        out = []
        for s in self.repos.sources.all(project_id):
            if s.source_type == SourceType.RESEARCH_PAPER and s.content_status == "PARSED":
                abstract = ""
                # best-effort abstract from first evidence of that source
                evs = [e for e in self.repos.evidence.all(project_id, "source_id=?", (s.id,))
                       if e.status.value != "REJECTED"]
                abstract = " ".join(e.claim_text for e in evs[:5])
                out.append({
                    "source_id": s.id, "title": s.title, "url": s.url,
                    "year": _year_of(s.publication_date),
                    "published": s.publication_date,
                    "citations": s.citation_count or 0,
                    "authors": s.author, "venue": s.publisher,
                    "abstract": abstract,
                })
        return out

    def build_map(self, project_id: str) -> dict:
        papers = self.collect_papers(project_id)
        clusters = cluster_papers(papers)
        return {
            "n_papers": len(papers),
            "clusters": [{
                "label": c.label, "size": len(c.papers), "top_terms": c.top_terms,
                "representative_papers": [
                    {"title": p["title"], "url": p["url"], "year": p["year"],
                     "citations": p["citations"]} for p in c.papers[:4]],
            } for c in clusters],
            "foundational": detect_foundational(papers),
            "recent": detect_recent_relevant(papers),
            "trend_by_year": publication_trend(papers),
            "trend_observation": trend_observation(publication_trend(papers)),
        }
