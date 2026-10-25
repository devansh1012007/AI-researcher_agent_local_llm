"""Keyless web search via DuckDuckGo HTML endpoints.

Fragile by nature (no official API); isolated here so providers can be swapped.
Also includes a SearXNG provider for users running a local metasearch instance.
"""
from __future__ import annotations

import logging
import re
from html import unescape
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx

from research_engine.core.http_policy import EgressPolicy
from research_engine.providers.search.base import (RawSearchHit, SearchProvider,
                                                    SearchProviderError)

log = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
       "(KHTML, like Gecko) Version/17.4 Safari/605.1.15")
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://duckduckgo.com/",
}

MAX_REDIRECTS = 10


def _request_with_redirect_check(method: str, url: str, policy: EgressPolicy | None,
                                 **kwargs) -> httpx.Response:
    """Perform an HTTP request, following 301/302/307/308 hops with per-hop
    egress validation.

    Mirrors the redirect loop in pipeline/fetching.py so a 302 to an external
    host cannot escape the pre-flight host check under LOCAL_ONLY. Auto-redirect
    is disabled (follow_redirects=False) and every ``Location`` host is
    re-validated through ``policy.require`` before being followed, bounded by
    ``MAX_REDIRECTS``.
    """
    current_url = url
    for _ in range(MAX_REDIRECTS):
        kwargs.pop("follow_redirects", None)
        if method.upper() == "GET":
            resp = httpx.get(current_url, follow_redirects=False, **kwargs)
        else:
            resp = httpx.post(current_url, follow_redirects=False, **kwargs)
        if resp.status_code in (301, 302, 307, 308):
            location = resp.headers.get("location")
            if not location:
                break
            redirect_url = urljoin(current_url, location)
            if policy is not None:
                policy.require(urlparse(redirect_url).hostname or "", "redirect")
            current_url = redirect_url
            continue
        return resp
    raise httpx.HTTPError("too many redirects")


def _decode_ddg_url(href: str) -> str:
    """DDG lite wraps results in /l/?uddg=<urlencoded>."""
    if "uddg=" in href:
        qs = parse_qs(urlparse(href).query)
        if "uddg" in qs:
            return unquote(qs["uddg"][0])
    return href


class DuckDuckGoProvider(SearchProvider):
    name = "duckduckgo"

    def __init__(self, timeout: float = 15.0, policy: EgressPolicy | None = None):
        self.timeout = timeout
        self.policy = policy

    def search(self, query: str, max_results: int = 10) -> list[RawSearchHit]:
        attempts = [
            ("GET", "https://html.duckduckgo.com/html/", {"q": query, "kb": "tf"}),
            ("GET", "https://lite.duckduckgo.com/lite/", {"q": query}),
            ("POST", "https://html.duckduckgo.com/html/", None),
        ]
        served = False
        for method, base, params in attempts:
            try:
                if self.policy is not None:
                    self.policy.require(urlparse(base).hostname, "duckduckgo search")
                if method == "GET":
                    resp = _request_with_redirect_check(method, base, self.policy,
                                                        params=params, headers=_HEADERS,
                                                        timeout=self.timeout)
                else:
                    resp = _request_with_redirect_check(method, base, self.policy,
                                                        data={"q": query}, headers=_HEADERS,
                                                        timeout=self.timeout)
                if resp.status_code != 200:
                    log.warning("ddg status %s from %s", resp.status_code, base)
                    continue
                served = True
                hits = self._parse(resp.text, max_results)
                if hits:
                    return hits
            except httpx.HTTPError as exc:
                log.warning("ddg attempt %s failed: %s", base, exc)
        if not served:
            # Every attempt failed: that is a provider failure, not an empty
            # result. See SearchProviderError.
            raise SearchProviderError("duckduckgo: all attempts failed")
        return []

    _NO_RESULTS_MARKERS = (
        "no results",
        "no more results",
        "did not match any documents",
        "no web pages were found",
    )
    _CHALLENGE_MARKERS = (
        "anomaly-modal",
        "bots use duckduckgo",
        "please complete the following challenge",
        "captcha",
        "access denied",
        "automated requests",
        "rate limit",
    )

    def _parse(self, html: str, max_results: int) -> list[RawSearchHit]:
        if not html or not html.strip():
            raise SearchProviderError("duckduckgo returned empty HTML body")
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
        if hits:
            return hits
        low = html.lower()
        if any(marker in low for marker in self._CHALLENGE_MARKERS):
            raise SearchProviderError("duckduckgo bot challenge or rate-limit interstitial")
        if any(marker in low for marker in self._NO_RESULTS_MARKERS) or 'class="no-results"' in low:
            return []
        raise SearchProviderError("duckduckgo returned unrecognized HTML structure without results or no-results marker")


class SearxngProvider(SearchProvider):
    name = "searxng"

    def __init__(self, base_url: str, timeout: float = 15.0,
                 policy: EgressPolicy | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.policy = policy

    def search(self, query: str, max_results: int = 10) -> list[RawSearchHit]:
        try:
            if self.policy is not None:
                self.policy.require(urlparse(f"{self.base_url}/search").hostname,
                                    "searxng search")
            resp = _request_with_redirect_check("GET", f"{self.base_url}/search", self.policy,
                                                params={"q": query, "format": "json"},
                                                headers={"User-Agent": _UA},
                                                timeout=self.timeout)
            resp.raise_for_status()
            out = []
            for r in resp.json().get("results", [])[:max_results]:
                out.append(RawSearchHit(url=r.get("url", ""), title=r.get("title", ""),
                                        snippet=r.get("content", ""),
                                        published_date=r.get("publishedDate")))
            return out
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("searxng failed: %s", exc)
            raise SearchProviderError(f"searxng: {exc}") from exc
