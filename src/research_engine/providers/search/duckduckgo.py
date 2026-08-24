"""Keyless web search via DuckDuckGo HTML endpoints.

Fragile by nature (no official API); isolated here so providers can be swapped.
Also includes a SearXNG provider for users running a local metasearch instance.
"""
from __future__ import annotations

import logging
import re
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from research_engine.providers.search.base import RawSearchHit, SearchProvider

log = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
       "(KHTML, like Gecko) Version/17.4 Safari/605.1.15")
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://duckduckgo.com/",
}


def _decode_ddg_url(href: str) -> str:
    """DDG lite wraps results in /l/?uddg=<urlencoded>."""
    if "uddg=" in href:
        qs = parse_qs(urlparse(href).query)
        if "uddg" in qs:
            return unquote(qs["uddg"][0])
    return href


class DuckDuckGoProvider(SearchProvider):
    name = "duckduckgo"

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    def search(self, query: str, max_results: int = 10) -> list[RawSearchHit]:
        attempts = [
            ("GET", "https://html.duckduckgo.com/html/", {"q": query, "kb": "tf"}),
            ("GET", "https://lite.duckduckgo.com/lite/", {"q": query}),
            ("POST", "https://html.duckduckgo.com/html/", None),
        ]
        for method, base, params in attempts:
            try:
                if method == "GET":
                    resp = httpx.get(base, params=params, headers=_HEADERS,
                                     timeout=self.timeout, follow_redirects=True)
                else:
                    resp = httpx.post(base, data={"q": query}, headers=_HEADERS,
                                      timeout=self.timeout, follow_redirects=True)
                if resp.status_code != 200:
                    log.warning("ddg status %s from %s", resp.status_code, base)
                    continue
                hits = self._parse(resp.text, max_results)
                if hits:
                    return hits
            except httpx.HTTPError as exc:
                log.warning("ddg attempt %s failed: %s", base, exc)
        return []

    def _parse(self, html: str, max_results: int) -> list[RawSearchHit]:
        hits: list[RawSearchHit] = []
        # result blocks: <a rel="nofollow" class="result__a" href="...">
        pattern = re.compile(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL
        )
        snippet_re = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
        snippets = [unescape(re.sub("<[^>]+>", "", s)).strip() for s in snippet_re.findall(html)]
        for i, m in enumerate(pattern.finditer(html)):
            url = _decode_ddg_url(unescape(m.group(1)))
            title = unescape(re.sub("<[^>]+>", "", m.group(2))).strip()
            if not url.startswith("http"):
                continue
            hits.append(RawSearchHit(url=url, title=title,
                                     snippet=snippets[i] if i < len(snippets) else ""))
            if len(hits) >= max_results:
                break
        return hits


class SearxngProvider(SearchProvider):
    name = "searxng"

    def __init__(self, base_url: str, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def search(self, query: str, max_results: int = 10) -> list[RawSearchHit]:
        try:
            resp = httpx.get(f"{self.base_url}/search", params={"q": query, "format": "json"},
                             headers={"User-Agent": _UA}, timeout=self.timeout)
            resp.raise_for_status()
            out = []
            for r in resp.json().get("results", [])[:max_results]:
                out.append(RawSearchHit(url=r.get("url", ""), title=r.get("title", ""),
                                        snippet=r.get("content", ""),
                                        published_date=r.get("publishedDate")))
            return out
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("searxng failed: %s", exc)
            return []
