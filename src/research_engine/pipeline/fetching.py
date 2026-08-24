"""Robust HTTP document fetcher: timeouts, backoff, size caps, caching, hashing.

Never downloads the same document twice within/across projects (global KV cache).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from research_engine.core.config import AppConfig
from research_engine.core.retry import NETWORK, run_with_retries
from research_engine.core.ids import stable_hash
from research_engine.storage.cache import KVCache, cache_key

log = logging.getLogger(__name__)


@dataclass
class FetchedContent:
    url: str
    final_url: str = ""
    status: int = 0
    content_type: str = ""
    body: bytes = b""
    from_cache: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 200 and not self.error

    @property
    def is_pdf(self) -> bool:
        ct = self.content_type.lower()
        return "pdf" in ct or self.body[:5] == b"%PDF-"

    @property
    def is_html(self) -> bool:
        ct = self.content_type.lower()
        return "html" in ct or (not ct and b"<html" in self.body[:2048].lower())

    @property
    def is_json(self) -> bool:
        return "json" in self.content_type.lower()


class DocumentFetcher:
    def __init__(self, cfg: AppConfig, cache: KVCache | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        self.cache = cache or KVCache(Path(cfg.storage.data_dir) / "_global" / "fetch_cache.sqlite")
        self.transport = transport  # injectable for offline tests
        self.max_bytes = int(cfg.resources.max_document_size_mb * 1024 * 1024)

    def fetch(self, url: str, force_refresh: bool = False) -> FetchedContent:
        key = cache_key("fetch", url)
        if not force_refresh:
            cached = self.cache.get(key)
            if cached is not None:
                return FetchedContent(url=url, final_url=cached.get("final_url", ""),
                                      status=cached.get("status", 0),
                                      content_type=cached.get("content_type", ""),
                                      body=b64decode(cached.get("body_b64", "")),
                                      from_cache=True)
        result = run_with_retries(self._do_fetch, NETWORK, on_failure="default", url=url,
                                  default=FetchedContent(url=url, error="all attempts failed"))
        if result.ok:
            self.cache.put(key, {"final_url": result.final_url, "status": result.status,
                                 "content_type": result.content_type,
                                 "body_b64": _b64encode(result.body)}, ttl_hours=168)
        return result

    def _do_fetch(self, url: str) -> FetchedContent:
        ncfg = self.cfg.network
        try:
            with httpx.Client(follow_redirects=True, timeout=ncfg.timeout_seconds,
                              headers={"User-Agent": ncfg.user_agent},
                              transport=self.transport) as client:
                with client.stream("GET", url) as resp:
                    if resp.status_code in (429, 503):
                        raise httpx.HTTPStatusError("rate limited", request=resp.request, response=resp)
                    body = bytearray()
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        body.extend(chunk)
                        if len(body) > self.max_bytes:
                            log.warning("document exceeds max size, truncating: %s", url)
                            break
                    return FetchedContent(
                        url=url, final_url=str(resp.url), status=resp.status_code,
                        content_type=resp.headers.get("content-type", ""),
                        body=bytes(body),
                    )
        except httpx.HTTPStatusError as exc:
            # non-retryable statuses fail fast; retryable ones re-raise for backoff
            code = exc.response.status_code
            if code in (429, 500, 502, 503, 504):
                raise
            return FetchedContent(url=url, status=code, error=f"http {code}")
        except httpx.HTTPError as exc:
            return FetchedContent(url=url, error=str(exc))

    def download_to(self, url: str, path) -> FetchedContent:
        """Fetch and persist raw bytes to disk."""
        fc = self.fetch(url)
        if fc.ok:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(fc.body)
        return fc


def _b64encode(b: bytes) -> str:
    import base64
    return base64.b64encode(b).decode()


def b64decode(s: str) -> bytes:
    import base64
    return base64.b64decode(s)


def body_of(cached: dict) -> bytes:
    import base64
    return base64.b64decode(cached.get("body_b64", ""))
