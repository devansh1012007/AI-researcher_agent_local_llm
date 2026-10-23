"""Identifier generation.

Two kinds of id live here:

* **Content ids** - ``stable_hash``, ``content_hash``, ``url_canonicalize`` and
  ``project_id_from_question`` are pure functions of their input: the same
  input always yields the same value, in any process, on any machine.
* **Entity ids** - ``next_id`` mints a *ULID*: ``<prefix>_<26 characters>``,
  where the 26 characters are Crockford base32 (no ``I``, ``L``, ``O`` or
  ``U``) encoding a 48-bit millisecond timestamp followed by 80 bits of
  randomness. The prefix is load-bearing - it discriminates types in the
  repositories, in natural keys, in graph prefixes and in CLI output - and is
  preserved.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import time

# Decision: entity ids are monotonic ULIDs, not a per-process counter.
# Why: the counter was process-global and had no persistence, so two
#   processes writing the same project database both minted `ev_000001`; the
#   upsert (`ON CONFLICT(id) DO UPDATE`) then silently OVERWROTE the first
#   row - data destruction with no error and nothing to notice.
# Constraint: the random component is incremented whenever another id is
#   minted in the same millisecond (or after the clock moves backwards), so
#   ids stay strictly increasing WITHIN one process. Across processes the
#   order inside one millisecond is NOT creation order.
#   A `fork()` WITHOUT a following `exec()` inherits the counter, so the
#   child re-seeds its random component on its first mint (see `next_id`).
#   An id is therefore NOT a global creation order: rows written before the
#   change keep their old `<prefix>_%06d` ids (which sort AFTER a ULID once
#   the counter passes 100000), the prefix differs per entity type, and
#   `storage/graph_store.py` relationships use a CONTENT hash. Consumers that
#   need creation order read the row payload's `created_at` instead - see
#   `storage/graph_store.py` and `specialists/startup/data_repair.py`.

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_TIME_CHARS = 10       # 48-bit millisecond timestamp (10 * 5 bits)
_ULID_RANDOM_CHARS = 16     # 80-bit random component (16 * 5 bits)
_RANDOM_LIMIT = 1 << 80

_lock = threading.Lock()
_last_ms = 0
_last_random = 0
_last_pid = 0


def _base32(value: int, length: int) -> str:
    """Fixed-width Crockford base32.

    Fixed width makes the encoding order-preserving: for two values that fit
    into ``length`` characters, ``a < b`` implies ``enc(a) < enc(b)`` as
    strings. That keeps the ids minted by ONE process comparable as text.
    It is not a global creation order - see the module comment.
    """
    out = []
    for _ in range(length):
        out.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


def next_id(prefix: str) -> str:
    """Collision-free, monotonic id: ``<prefix>_<26-char Crockford base32>``."""
    global _last_ms, _last_random, _last_pid
    with _lock:
        now_ms = int(time.time() * 1000)
        pid = os.getpid()
        forked = pid != _last_pid
        if forked:
            _last_pid = pid
        if now_ms > _last_ms:
            _last_ms = now_ms
            # When the millisecond advances, we draw fresh entropy via os.urandom;
            # a forked child does NOT inherit this new random component. If a fork
            # happens within the same millisecond, the child inherits `_last_random`
            # and will compute the same increment as the parent, causing a collision.
            _last_random = int.from_bytes(os.urandom(10), "big")
        elif forked:
            # Decision: a forked child RE-SEEDS its random component.
            # Why: the child inherits the parent's counter, so the
            # same-millisecond branch would compute the SAME increment the
            # parent computes and mint a byte-identical id. Re-seeding on
            # the first mint after the pid change breaks that.
            # Constraint: only the random component is re-seeded; the
            # millisecond stamp is kept, so the id stays a valid ULID. The
            # order ACROSS processes is not a creation order anyway (see
            # the module comment).
            _last_random = int.from_bytes(os.urandom(10), "big")
        else:
            # Same millisecond, or the clock moved backwards: increment the
            # random component instead of drawing a new one, so the id is
            # strictly greater than the previously minted one.
            _last_random += 1
            if _last_random >= _RANDOM_LIMIT:
                # 2**80 ids in one millisecond: carry into the timestamp.
                _last_random = 0
                _last_ms += 1
        body = (_base32(_last_ms, _ULID_TIME_CHARS)
                + _base32(_last_random, _ULID_RANDOM_CHARS))
    return f"{prefix}_{body}"


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
