"""Platform-store accessor for adaptive components.

Project-scoped objects (orchestrator, repos) sometimes need read access to
platform-level learning stores. This module caches one PlatformDB per
data_dir so adaptive lookups don't proliferate connections.
"""
from __future__ import annotations

import threading

from research_engine.storage.platform_db import PlatformDB

_cache: dict[str, PlatformDB] = {}
_lock = threading.Lock()


def platform_store(data_dir: str) -> PlatformDB:
    key = str(data_dir)
    with _lock:
        db = _cache.get(key)
        if db is None:
            db = PlatformDB(key)
            _cache[key] = db
        return db


def reset_cache() -> None:
    """Test isolation hook."""
    with _lock:
        for db in _cache.values():
            try:
                db.close()
            except Exception:
                pass
        _cache.clear()
