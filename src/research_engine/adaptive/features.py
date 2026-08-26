"""Task feature extraction (Phase 6 §8) and domain bucketing (§10).

Deterministic keyword/structure features describing a research problem.
These let the system compare similar tasks WITHOUT an LLM and keep routing
explainable: every feature is derivable from the question text alone.
Coarse by design — §10 forbids overfitting from handfuls of examples.
"""
from __future__ import annotations

import re

# Domain buckets are deliberately coarse; a specialist being strong on
# "B2B SaaS" vs "regulated healthcare" (§10) is expressible with these.
_BUCKET_SIGNALS: dict[str, list[str]] = {
    "regulated_industry": [
        "healthcare", "medical", "clinical", "fda", "hipaa", "patient",
        "pharma", "financial regulation", "compliance", "gdpr", "legal",
        "insurance", "banking",
    ],
    "b2b_saas": [
        "saas", "b2b", "enterprise software", "api platform", "workflow",
        "crm", "erp", "devtools", "developer tool", "integration platform",
    ],
    "consumer": [
        "consumer app", "social", "marketplace for consumers", "gaming",
        "creator", "e-commerce shopper", "mobile app users",
    ],
    "technical_science": [
        "algorithm", "model architecture", "benchmark", "protocol",
        "physics", "chemistry", "biology", "materials", "robotics",
        "sensor fusion", "dataset", "method comparison",
    ],
}

_TECHNICAL = [
    "algorithm", "architecture", "latency", "throughput", "prototype",
    "constraint", "gpu", "compute requirement", "integration", "accuracy",
]
_MARKET = [
    "market", "customer", "willingness to pay", "pricing", "competitor",
    "segment", "revenue", "adoption", "go-to-market",
]
_CURRENT = [
    "latest", "recent", "2024", "2025", "2026", "state of the art",
    "this year", "new release", "emerging",
]
_PRIMARY = [
    "primary source", "original paper", "official documentation", "fda filing",
    "patent", "sec filing", "regulatory filing", "first-party data",
]

_WORD = re.compile(r"[a-z0-9]+")


def _hits(text: str, vocab: list[str]) -> int:
    return sum(1 for k in vocab if k in text)


def _ratio(hits: int) -> float:
    return round(min(1.0, hits / 3.0), 3)


def domain_bucket(question: str) -> str:
    """One of five coarse buckets; 'broad_exploratory' is the default."""
    text = (question or "").lower()
    scores = {b: _hits(text, v) for b, v in _BUCKET_SIGNALS.items()}
    best = max(scores, key=lambda b: scores[b])
    return best if scores[best] > 0 else "broad_exploratory"


def extract_task_features(question: str, mode: str,
                          subquestions: list[str] | None = None) -> dict:
    """Structured research-problem features (spec §8). Pure function."""
    text = (question or "").lower()
    subs = [s for s in (subquestions or []) if s]
    n_subq = len(subs)
    complexity = "low" if n_subq <= 2 else ("medium" if n_subq <= 5 else "high")
    return {
        "domain_bucket": domain_bucket(question),
        "research_type": mode or "",
        "num_subquestions": n_subq,
        "complexity": complexity,
        "technicality": _ratio(_hits(text, _TECHNICAL)),
        "market_orientation": _ratio(_hits(text, _MARKET)),
        "current_info_need": _ratio(_hits(text, _CURRENT)),
        "primary_source_need": _ratio(_hits(text, _PRIMARY)),
        "cross_domain": bool(
            _hits(text, _TECHNICAL) >= 1 and _hits(text, _MARKET) >= 1),
        "time_sensitivity": 1.0 if _hits(text, _CURRENT) >= 1 else 0.0,
        "geographic_specificity": 1.0 if re.search(
            r"\b(in|across|for)\s+[a-z]+( market| region| countries)",
            text) else 0.0,
    }
