"""Canonical entity identity for startup domain objects (INVARIANT-003).

Every specialist entity resolves against a NATURAL KEY before persisting.
Repeated analysis must converge to the same underlying rows — running an
analyzer twice must not mint new identities.

Identity decisions are domain-specific (spec §14):
    market        -> (project, market_slug)
    size estimate -> (project, source_evidence)   one figure per evidence
    persona       -> (project, segment)            one persona per segment
    jtbd          -> (project, segment)
    alternative   -> (project, normalized name)
    competitor    -> (project, normalized company name)
    pricing plan  -> (project, vendor, raw price token, billing period)
    channel       -> (project, channel name)
    tech shift    -> (project, description fingerprint)

Company-name normalization strips legal suffixes/punctuation so
"OpenAI", "OpenAI, Inc." and "Open AI Inc" resolve together — while
distinct names never merge (conservative normalization only).
"""
from __future__ import annotations

import hashlib
import re

_LEGAL_SUFFIXES = (
    " inc", " inc.", " incorporated", " llc", " l.l.c", " ltd", " limited",
    " gmbh", " ag", " sa", " sas", " bv", " oy", " ab", " pvt", " pvt.",
    " private", " corp", " corp.", " corporation", " co", " co.", " company",
)


def norm_name(name: str) -> str:
    """Conservative canonical form for company/product/persona names."""
    s = re.sub(r"[^\w\s]", " ", (name or "").lower())
    s = re.sub(r"\s+", " ", s).strip()
    changed = True
    while changed:
        changed = False
        for suf in _LEGAL_SUFFIXES:
            if s.endswith(suf):
                s = s[: -len(suf)].strip()
                changed = True
    return s


def price_key(price_raw: str, currency: str, period: str) -> str:
    """Canonical token for a pricing observation (raw string is sacred for
    display; identity uses the normalized amount token)."""
    tok = re.sub(r"[^\d.,]", "", price_raw or "").strip(".,")
    return f"{tok}|{(currency or '').upper()}|{period or 'unknown'}"


def desc_fingerprint(text: str, limit: int = 100) -> str:
    toks = re.findall(r"[a-z0-9]+", (text or "").lower())
    return hashlib.sha1(" ".join(toks[:limit]).encode()).hexdigest()[:16]


# strength ordering for channel-evidence classes
_CHANNEL_CLASS_RANK = {"observed": 2, "inferred": 1, "hypothesized": 0}


def strongest_class(a: str, b: str) -> str:
    return a if _CHANNEL_CLASS_RANK.get(a, 0) >= _CHANNEL_CLASS_RANK.get(b, 0) else b


_LIST_FIELDS = {
    "Market": ["boundaries", "exclusions", "related_markets", "segments",
               "drivers", "constraints", "technology_drivers",
               "definition_gaps", "evidence_ids"],
    "Persona": ["responsibilities", "pain_points", "existing_tools",
                "evidence_ids"],
    "JobToBeDone": ["workflow_steps", "pain_ids", "evidence_ids"],
    "CurrentAlternative": ["used_by_segments", "evidence_ids"],
    "CompetitorProfile": ["features", "integrations", "distribution_channels",
                          "strengths", "weaknesses", "recent_changes",
                          "evidence_ids"],
    "TechnologyShift": ["evidence_ids"],
    "DistributionChannel": ["used_by"],
}
_DICT_FIELDS = {"CompetitorProfile": ["channel_evidence"]}


def merge_entities(existing, incoming):
    """Merge an incoming analysis snapshot INTO the persisted entity.
    List-typed fields union (provenance preserved); scalar fields take the
    incoming value when the incoming carries one. Returns merged model."""
    cls_name = type(existing).__name__
    data = incoming.model_dump()
    for field in _LIST_FIELDS.get(cls_name, []):
        have = list(getattr(existing, field, []) or [])
        for item in (data.get(field) or []):
            if item not in have:
                have.append(item)
        setattr(existing, field, have)
    for field in _DICT_FIELDS.get(cls_name, []):
        merged = dict(getattr(existing, field, {}) or {})
        merged.update(data.get(field) or {})
        setattr(existing, field, merged)
    for field, value in data.items():
        if field in ("id", "created_at", "project_id"):
            continue
        if field in _LIST_FIELDS.get(cls_name, []) or \
                field in _DICT_FIELDS.get(cls_name, []):
            continue
        current = getattr(existing, field, None)
        if value not in (None, "", [], {}) and (current in (None, "", [], {}) or
                                                field.endswith("_at")):
            setattr(existing, field, value)
    return existing
