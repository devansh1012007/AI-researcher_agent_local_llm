"""Labelled gold fixtures for the offline quality benchmark (C17, D.4, D.7, D.8).

Every item is content-keyed: identity is sha256 of normalised content, so it
survives id-format changes and can be re-labelled without breaking references.

Item kinds:
  * support - a (claim, quote) pair with a human label: SUPPORTED / NOT_SUPPORTED
    Key: sha256(norm(claim_text) + "\x00" + norm(quote))
  * contradiction - a (claim_a, claim_b) pair with a human label:
    CONTRADICTS / NOT_CONTRADICTS
    Key: sha256(sorted([norm(claim_a), norm(claim_b)]))
  * opportunity - a startup opportunity with a human-ranked priority score
    Key: sha256(norm(question) + "\x00" + norm(opportunity_text))
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

GOLD_DIR = Path(__file__).resolve().parent


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def support_key(claim_text: str, quote: str) -> str:
    """Content key for a support pair item (D.4)."""
    return _sha(_norm(claim_text) + "\x00" + _norm(quote))


def contradiction_key(claim_a: str, claim_b: str) -> str:
    """Content key for a contradiction pair item (D.4)."""
    a, b = sorted([_norm(claim_a), _norm(claim_b)])
    return _sha(a + "\x00" + b)


def opportunity_key(question: str, opportunity_text: str) -> str:
    """Content key for an opportunity fixture item."""
    return _sha(_norm(question) + "\x00" + _norm(opportunity_text))


def load_gold_items(path: Path | str | None = None) -> list[dict[str, Any]]:
    """Load labelled gold items from a JSONL file.

    Each line is a JSON object with at least: kind, label, and the
    content fields needed to compute the content key. The key is added
    by this function if absent.
    """
    p = Path(path) if path else GOLD_DIR / "gold_items.jsonl"
    items: list[dict[str, Any]] = []
    if not p.exists():
        return items
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        item = json.loads(line)
        kind = item["kind"]
        if kind == "support":
            item.setdefault("key", support_key(item["claim_text"], item["quote"]))
        elif kind == "contradiction":
            item.setdefault("key", contradiction_key(item["claim_a"], item["claim_b"]))
        elif kind == "opportunity":
            item.setdefault("key", opportunity_key(item["question"], item["opportunity_text"]))
        items.append(item)
    return items


# ---------------------------------------------------------------------------
# Starter labelled fixtures (human-labelled, content-keyed)
# ---------------------------------------------------------------------------

STARTER_ITEMS: list[dict[str, Any]] = [
    # --- support pairs ---
    {
        "kind": "support",
        "claim_text": "RAG improves factual accuracy of language models",
        "quote": "Our experiments show RAG reduces hallucination rates by 42% compared to vanilla LLMs",
        "label": "SUPPORTED",
        "source": "paper_2024_rag_eval",
    },
    {
        "kind": "support",
        "claim_text": "RAG eliminates all hallucinations",
        "quote": "RAG reduces but does not eliminate hallucinations; residual errors remain",
        "label": "NOT_SUPPORTED",
        "source": "paper_2024_rag_eval",
    },
    {
        "kind": "support",
        "claim_text": "Small businesses in India need affordable AI infrastructure",
        "quote": "78% of Indian SMBs cite cost as the primary barrier to AI adoption",
        "label": "SUPPORTED",
        "source": "survey_2024_indi_smb",
    },
    # --- contradiction pairs ---
    {
        "kind": "contradiction",
        "claim_a": "RAG improves factual accuracy",
        "claim_b": "RAG introduces more errors than it fixes",
        "label": "CONTRADICTS",
        "source": "paper_2024_rag_eval vs paper_2024_rag_critique",
    },
    {
        "kind": "contradiction",
        "claim_a": "AI infrastructure is affordable for Indian SMBs",
        "claim_b": "Cost is the primary barrier to AI adoption for Indian SMBs",
        "label": "CONTRADICTS",
        "source": "survey_2024_indi_smb vs vendor_claim_2024",
    },
    {
        "kind": "contradiction",
        "claim_a": "Market size for industrial robotics was $15B in 2023",
        "claim_b": "Market size for industrial robotics was $25B in 2023",
        "label": "CONTRADICTS",
        "source": "report_2024_robotics_a vs report_2024_robotics_b",
    },
    # --- opportunity fixtures ---
    {
        "kind": "opportunity",
        "question": "AI infrastructure for small businesses in India",
        "opportunity_text": "Low-cost AI inference hosting for Indian SMBs",
        "label": "HIGH_PRIORITY",
        "score": 0.85,
    },
    {
        "kind": "opportunity",
        "question": "AI infrastructure for small businesses in India",
        "opportunity_text": "Enterprise-grade MLOps platform for Fortune 500",
        "label": "LOW_PRIORITY",
        "score": 0.25,
    },
]


def write_starter_fixtures() -> Path:
    """Write the starter labelled fixtures to gold_items.jsonl (idempotent)."""
    out = GOLD_DIR / "gold_items.jsonl"
    if out.exists():
        return out
    with out.open("w", encoding="utf-8") as f:
        for item in STARTER_ITEMS:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return out
