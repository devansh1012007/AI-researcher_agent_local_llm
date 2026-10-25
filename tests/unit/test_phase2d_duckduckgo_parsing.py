"""Phase 2D tests: DuckDuckGo parsing distinguishes results, explicit no-results, challenge, and unknown HTML (P1-16)."""
from __future__ import annotations

import pytest
from research_engine.providers.search.base import SearchProviderError
from research_engine.providers.search.duckduckgo import DuckDuckGoProvider


def test_ddg_parse_valid_results():
    html = """
    <html><body>
      <div class="result">
        <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fpaper">Example Paper</a>
        <a class="result__snippet">A snippet about RAG factuality.</a>
      </div>
    </body></html>
    """
    hits = DuckDuckGoProvider()._parse(html, max_results=5)
    assert len(hits) == 1
    assert hits[0].url == "https://example.org/paper"
    assert hits[0].title == "Example Paper"
    assert "RAG factuality" in hits[0].snippet


def test_ddg_parse_explicit_no_results_returns_empty_list():
    html = "<html><body><div class='no-results'>No results found for your query.</div></body></html>"
    assert DuckDuckGoProvider()._parse(html, max_results=5) == []


def test_ddg_parse_challenge_page_raises_search_provider_error():
    html = "<html><body><div class='anomaly-modal'>Unfortunately, bots use DuckDuckGo too. Please complete the following challenge.</div></body></html>"
    with pytest.raises(SearchProviderError, match="challenge"):
        DuckDuckGoProvider()._parse(html, max_results=5)


def test_ddg_parse_unrecognized_markup_raises_search_provider_error():
    html = "<html><body><div>Completely redesigned page with neither results nor no-results marker</div></body></html>"
    with pytest.raises(SearchProviderError, match="unrecognized HTML"):
        DuckDuckGoProvider()._parse(html, max_results=5)


def test_ddg_parse_empty_body_raises_search_provider_error():
    with pytest.raises(SearchProviderError, match="empty HTML"):
        DuckDuckGoProvider()._parse("   ", max_results=5)
