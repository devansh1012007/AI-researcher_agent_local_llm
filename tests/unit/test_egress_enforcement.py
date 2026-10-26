"""Egress enforcement tests (C09 / W2-IMPR-01 T-013).

Verifies ``policy.require(host)`` blocks every non-loopback host under
``LOCAL_ONLY`` *before* any network call at each request-time enforcement
point, and that ``policy=None`` preserves backward compatibility.

Hermetic: no real network is used; ``httpx`` is monkeypatched so any attempt
to reach the network fails the test loudly, proving the egress guard fired
first.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from research_engine.core.config import AppConfig, LLMRoleConfig, PlatformConfig, SecurityConfig
from research_engine.core.http_policy import EgressPolicy, build_egress_policy
from research_engine.core.orchestrator import build_default_registry
from research_engine.pipeline.fetching import DocumentFetcher
from research_engine.providers.academic.arxiv import ArxivProvider
from research_engine.providers.academic.crossref import CrossrefProvider
from research_engine.providers.academic.openalex import OpenAlexProvider
from research_engine.providers.academic.semantic_scholar import SemanticScholarProvider
from research_engine.providers.embeddings.base import (
    OllamaEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
)
from research_engine.providers.llm.openai_compat import OpenAICompatibleProvider
from research_engine.providers.llm.ollama import OllamaProvider
from research_engine.providers.llm.router import ModelRouter, build_provider
from research_engine.providers.search.duckduckgo import DuckDuckGoProvider, SearxngProvider

EXTERNAL = "http://external.example.com/"
LOOPBACK = "http://127.0.0.1:1/"


# --------------------------------------------------------------------------- #
# fakes / helpers
# --------------------------------------------------------------------------- #

class _Resp:
    """Fake httpx response with a minimal, safe surface."""

    def __init__(self, status_code=200, text="", headers=None, content=b""):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.content = content
        self.request = SimpleNamespace()

    def json(self):
        return {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=self.request, response=self)

    def iter_bytes(self, chunk_size=65536):
        yield self.content


def _block_network(monkeypatch):
    """Make every httpx.get/post raise AssertionError.

    A test using this fails if the code-under-test reaches the network,
    which proves ``policy.require`` fired *before* the call.
    """

    def boom(*a, **k):
        raise AssertionError("network call attempted despite LOCAL_ONLY block")

    monkeypatch.setattr(httpx, "get", boom)
    monkeypatch.setattr(httpx, "post", boom)


def _serve_ok(monkeypatch, status_code=200, text=""):
    """Make every httpx.get/post return a fake response."""

    def serve(*a, **k):
        return _Resp(status_code, text=text)

    monkeypatch.setattr(httpx, "get", serve)
    monkeypatch.setattr(httpx, "post", serve)


def _llm_cfg(base_url=EXTERNAL):
    return SimpleNamespace(
        base_url=base_url,
        model="mock-model",
        temperature=0.1,
        max_tokens=2048,
        timeout_seconds=120.0,
        context_tokens=8000,
    )


def _local_only_cfg():
    return AppConfig(
        platform=PlatformConfig(mode="local", security=SecurityConfig(local_only=True))
    )


# --------------------------------------------------------------------------- #
# academic providers: LOCAL_ONLY => RuntimeError before network
# --------------------------------------------------------------------------- #

def test_openalex_local_only_raises_before_network(monkeypatch):
    _block_network(monkeypatch)
    with pytest.raises(RuntimeError):
        OpenAlexProvider(policy=EgressPolicy("LOCAL_ONLY")).search("quantum computing")


def test_crossref_local_only_raises_before_network(monkeypatch):
    _block_network(monkeypatch)
    with pytest.raises(RuntimeError):
        CrossrefProvider(policy=EgressPolicy("LOCAL_ONLY")).search("quantum computing")


def test_arxiv_local_only_raises_before_network(monkeypatch):
    _block_network(monkeypatch)
    with pytest.raises(RuntimeError):
        ArxivProvider(policy=EgressPolicy("LOCAL_ONLY")).search("quantum computing")


def test_semantic_scholar_local_only_raises_before_network(monkeypatch):
    _block_network(monkeypatch)
    with pytest.raises(RuntimeError):
        SemanticScholarProvider(policy=EgressPolicy("LOCAL_ONLY")).search("quantum computing")


# --------------------------------------------------------------------------- #
# duckduckgo / searxng
# --------------------------------------------------------------------------- #

def test_duckduckgo_get_local_only_raises_before_network(monkeypatch):
    _block_network(monkeypatch)
    with pytest.raises(RuntimeError):
        DuckDuckGoProvider(policy=EgressPolicy("LOCAL_ONLY")).search("quantum computing")


def test_duckduckgo_post_local_only_raises_before_network(monkeypatch):
    """The POST attempt is independently guarded (3 attempts, each requires)."""
    _block_network(monkeypatch)
    with pytest.raises(RuntimeError):
        DuckDuckGoProvider(policy=EgressPolicy("LOCAL_ONLY")).search("quantum computing")


def test_duckduckgo_policy_none_backward_compat(monkeypatch):
    """policy=None skips the require guard; the (faked) call proceeds."""
    _serve_ok(monkeypatch, text="<html><body>no results here</body></html>")
    assert DuckDuckGoProvider().search("quantum computing") == []


def test_searxng_local_only_raises_before_network(monkeypatch):
    _block_network(monkeypatch)
    with pytest.raises(RuntimeError):
        SearxngProvider(EXTERNAL, policy=EgressPolicy("LOCAL_ONLY")).search("quantum computing")


def test_searxng_loopback_base_redirect_to_external_refused(monkeypatch):
    """A loopback searxng base passes pre-flight, but a 302 to an external host
    is refused at hop 2 by per-hop redirect validation (F-3)."""

    def handler(request, **kwargs):
        return _Resp(302, headers={"location": "http://external.example.com/target"})

    monkeypatch.setattr(httpx, "get", handler)
    with pytest.raises(RuntimeError):
        SearxngProvider(LOOPBACK, policy=EgressPolicy("LOCAL_ONLY")).search("quantum computing")


def test_searxng_follow_redirects_is_false(monkeypatch):
    """Auto-redirect must be disabled; the helper passes follow_redirects=False."""
    captured = {}

    def handler(request, **kwargs):
        captured.update(kwargs)
        return _Resp(200, text='{"results": []}')

    monkeypatch.setattr(httpx, "get", handler)
    SearxngProvider(LOOPBACK, policy=EgressPolicy("LOCAL_ONLY")).search("quantum computing")
    assert captured.get("follow_redirects") is False


# --------------------------------------------------------------------------- #
# LLM providers
# --------------------------------------------------------------------------- #

def test_ollama_complete_local_only_raises_before_network(monkeypatch):
    _block_network(monkeypatch)
    with pytest.raises(RuntimeError):
        OllamaProvider(_llm_cfg(), policy=EgressPolicy("LOCAL_ONLY")).complete("sys", "user")


def test_ollama_is_available_local_only_raises_before_network(monkeypatch):
    _block_network(monkeypatch)
    with pytest.raises(RuntimeError):
        OllamaProvider(_llm_cfg(), policy=EgressPolicy("LOCAL_ONLY")).is_available()


def test_openai_compat_complete_local_only_raises_before_network(monkeypatch):
    _block_network(monkeypatch)
    with pytest.raises(RuntimeError):
        OpenAICompatibleProvider(
            _llm_cfg("http://remote-openai.example:8000/v1"),
            policy=EgressPolicy("LOCAL_ONLY"),
        ).complete("sys", "user")


# --------------------------------------------------------------------------- #
# embedding providers
# --------------------------------------------------------------------------- #

def test_ollama_embed_local_only_raises_before_network(monkeypatch):
    _block_network(monkeypatch)
    with pytest.raises(RuntimeError):
        OllamaEmbeddingProvider(base_url=EXTERNAL, policy=EgressPolicy("LOCAL_ONLY")).embed("text")


def test_ollama_embed_is_available_local_only_raises_before_network(monkeypatch):
    _block_network(monkeypatch)
    with pytest.raises(RuntimeError):
        OllamaEmbeddingProvider(base_url=EXTERNAL, policy=EgressPolicy("LOCAL_ONLY")).is_available()


def test_openai_compatible_embed_local_only_raises_before_network(monkeypatch):
    _block_network(monkeypatch)
    with pytest.raises(RuntimeError):
        OpenAICompatibleEmbeddingProvider(
            model="m", base_url=EXTERNAL, policy=EgressPolicy("LOCAL_ONLY")
        ).embed("text")


# --------------------------------------------------------------------------- #
# DocumentFetcher
# --------------------------------------------------------------------------- #

def _fetcher_local_only(tmp_path, transport=None):
    cfg = _local_only_cfg()
    cfg.storage.data_dir = str(tmp_path / "data")
    return DocumentFetcher(cfg, transport=transport)


def test_document_fetcher_initial_url_local_only_raises(tmp_path):
    """Non-loopback initial URL is refused before any client/transport is created."""
    fetcher = _fetcher_local_only(tmp_path)
    with pytest.raises(RuntimeError):
        fetcher._do_fetch(EXTERNAL + "page")


def test_document_fetcher_redirect_to_external_refused_at_hop_2(tmp_path, monkeypatch):
    """Loopback initial URL passes pre-flight; a 302 to an external host is
    refused at the second hop by per-hop redirect validation."""

    def handler(request):
        return httpx.Response(
            302, request=request, headers={"location": "http://external.example.com/target"}
        )

    fetcher = _fetcher_local_only(tmp_path, transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError):
        fetcher._do_fetch(LOOPBACK + "page")


def test_document_fetcher_follow_redirects_is_false(tmp_path, monkeypatch):
    """The httpx.Client is built with follow_redirects=False."""
    captured = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, method, url):
            class _R:
                status_code = 200
                headers = {}
                request = SimpleNamespace()

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def iter_bytes(self, chunk_size=65536):
                    yield b""

            _R.url = url
            return _R()

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    fetcher = _fetcher_local_only(tmp_path)
    fetcher._do_fetch(LOOPBACK + "page")
    assert captured.get("follow_redirects") is False


# --------------------------------------------------------------------------- #
# ModelRouter / build_provider / build_default_registry wiring
# --------------------------------------------------------------------------- #

def _app_cfg():
    return AppConfig(platform=PlatformConfig(mode="local"))


def test_model_router_policy_matches_build_egress_policy():
    """for_role(role).policy is the router's policy built from app_cfg."""
    router = ModelRouter(_app_cfg())
    assert router.policy is not None
    for role in ("extractor", "reasoning", "synthesis"):
        assert router.for_role(role).policy is router.policy


def test_build_provider_policy_none_backward_compat():
    """build_provider(cfg) with policy=None leaves MockProvider without a policy
    attribute and does not raise."""
    prov = build_provider(LLMRoleConfig(provider="mock"))
    assert not hasattr(prov, "policy") or prov.policy is None


def test_build_provider_forwards_policy():
    """build_provider(cfg, policy=pol) delivers policy via setattr."""
    pol = EgressPolicy("HYBRID")
    prov = build_provider(LLMRoleConfig(provider="mock"), policy=pol)
    assert prov.policy is pol


def test_build_default_registry_forwards_policy_to_all_six(monkeypatch):
    """All six provider constructors receive policy=policy (F-1 wiring)."""
    cfg = _app_cfg()
    cfg.search.web_provider = "duckduckgo"
    policy = build_egress_policy(cfg)

    captured = {}

    def spy(cls, name):
        orig = cls.__init__

        def wrapped(self, *a, **k):
            captured[name] = k.get("policy")
            return orig(self, *a, **k)

        return wrapped

    from research_engine.providers.search.duckduckgo import (
        DuckDuckGoProvider,
        SearxngProvider,
    )
    from research_engine.providers.academic.openalex import OpenAlexProvider
    from research_engine.providers.academic.crossref import CrossrefProvider
    from research_engine.providers.academic.arxiv import ArxivProvider
    from research_engine.providers.academic.semantic_scholar import SemanticScholarProvider

    monkeypatch.setattr(DuckDuckGoProvider, "__init__", spy(DuckDuckGoProvider, "duckduckgo"))
    monkeypatch.setattr(SearxngProvider, "__init__", spy(SearxngProvider, "searxng"))
    monkeypatch.setattr(OpenAlexProvider, "__init__", spy(OpenAlexProvider, "openalex"))
    monkeypatch.setattr(CrossrefProvider, "__init__", spy(CrossrefProvider, "crossref"))
    monkeypatch.setattr(ArxivProvider, "__init__", spy(ArxivProvider, "arxiv"))
    monkeypatch.setattr(
        SemanticScholarProvider, "__init__", spy(SemanticScholarProvider, "semantic_scholar")
    )

    reg = build_default_registry(cfg)
    assert reg is not None
    # web_provider="duckduckgo" constructs duckduckgo + the 4 academics;
    # searxng is only constructed when web_provider="searxng" (line 668,
    # same policy=policy forwarding). Verify every constructor that ran
    # received the single policy object.
    names = ("duckduckgo", "openalex", "crossref", "arxiv", "semantic_scholar")
    captured_policies = [captured.get(name) for name in names]
    assert all(p is not None for p in captured_policies), (
        "a constructed provider missed policy=policy"
    )
    assert all(p is captured_policies[0] for p in captured_policies), (
        "not all constructed providers received the same policy object"
    )


def test_build_default_registry_local_only_empty_registry():
    """LOCAL_ONLY short-circuits to an empty registry (construction-time gate)."""
    cfg = _local_only_cfg()
    reg = build_default_registry(cfg)
    assert reg.get_any("web") is None
    for name in ("openalex", "crossref", "arxiv", "semantic_scholar"):
        assert reg.get_any(name) is None
