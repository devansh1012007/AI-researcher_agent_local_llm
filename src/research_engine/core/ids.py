"""Stable, deterministic identifier generation."""
from __future__ import annotations

import hashlib
import itertools
import re
import threading

_lock = threading.Lock()
_counters: dict[str, int] = {}


def next_id(prefix: str) -> str:
    """Sequential ID like ev_000042. Deterministic within a process; DB stores them."""
    with _lock:
        _counters[prefix] = _counters.get(prefix, 0) + 1
        n = _counters[prefix]
    return f"{prefix}_{n:06d}"


def seed_counter(prefix: str, value: int) -> None:
    with _lock:
        _counters[prefix] = max(_counters.get(prefix, 0), value)


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(text: str) -> str:
    """Normalized content hash used for document dedup."""
    normalized = re.sub(r"\s+", " ", text or "").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def url_canonicalize(url: str) -> str:
    """Cheap canonicalization: strip fragments/tracking params, lowercase host."""
    url = (url or "").strip()
    url = re.sub(r"^https?://", "", url)
    url = url.split("#", 1)[0]
    # lowercase only the host portion; paths may be case-sensitive
    host_sep = url.find("/")
    if host_sep == -1:
        url = url.lower()
    else:
        url = url[:host_sep].lower() + url[host_sep:]
    # strip common tracking query params
    if "?" in url:
        base, _, qs = url.partition("?")
        keep = [
            p
            for p in qs.split("&")
            if p and not p.split("=", 1)[0].lower()
            in {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid", "ref"}
        ]
        url = base + ("?" + "&".join(keep) if keep else "")
    return url.rstrip("/")


def project_id_from_question(question: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:48]
    digest = stable_hash(question)[:8]
    return f"proj_{slug}-{digest}"
