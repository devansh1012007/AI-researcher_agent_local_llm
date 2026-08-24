"""arXiv API provider. No key required. Returns Atom XML."""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

import httpx

from research_engine.providers.academic.base import AcademicProvider, clean_query
from research_engine.providers.search.base import RawSearchHit

log = logging.getLogger(__name__)

_NS = {"a": "http://www.w3.org/2005/Atom"}


class ArxivProvider(AcademicProvider):
    name = "arxiv"
    BASE = "https://export.arxiv.org/api/query"

    def __init__(self, timeout: float = 25.0):
        self.timeout = timeout

    def search(self, query: str, max_results: int = 10) -> list[RawSearchHit]:
        # arXiv prefers fielded queries; raw text usually works in all: mode
        q = clean_query(query)
        try:
            resp = httpx.get(self.BASE, params={
                "search_query": f"all:{q}",
                "start": 0,
                "max_results": min(max_results, 30),
                "sortBy": "relevance",
            }, timeout=self.timeout)
            resp.raise_for_status()
            return self._parse(resp.text)
        except (httpx.HTTPError, ET.ParseError) as exc:
            log.warning("arxiv search failed: %s", exc)
            return []

    def _parse(self, xml_text: str) -> list[RawSearchHit]:
        root = ET.fromstring(xml_text)
        out = []
        for entry in root.findall("a:entry", _NS):
            def _t(tag):
                el = entry.find(tag, _NS)
                return re.sub(r"\s+", " ", el.text or "").strip() if el is not None else ""
            pdf_url = ""
            for link in entry.findall("a:link", _NS):
                if link.get("title") == "pdf":
                    pdf_url = link.get("href", "")
            out.append(RawSearchHit(
                url=_t("a:id"),
                title=_t("a:title"),
                snippet=_t("a:summary")[:1500],
                published_date=_t("a:published")[:10] or None,
                metadata={
                    "provider": self.name,
                    "authors": [a.findtext("a:name", "", _NS)
                                for a in entry.findall("a:author", _NS)[:8]],
                    "venue": "arXiv",
                    "pdf_url": pdf_url,
                    "primary_category": (entry.find("a:category", _NS) is not None and
                                         entry.find("a:category", _NS).get("term", "")) or "",
                },
            ))
        return out
