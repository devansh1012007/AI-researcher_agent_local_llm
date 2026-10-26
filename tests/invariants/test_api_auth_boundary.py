"""INV-014: the API requires a token exactly when the server is bound to a
non-loopback address.

The bug this guards: `research serve --host 0.0.0.0` bound every interface
while the app authorised on the CONFIGURED host (127.0.0.1), so the whole API
was served unauthenticated — and `Dockerfile`'s CMD is exactly that command.

Decision (owner): loopback stays unauthenticated. That makes the bind
address the ONLY auth boundary, so the address the server binds and the
address the app authorises on must be the same value — and both must use the
same fail-closed predicate.
"""
from __future__ import annotations

import pytest


class TestApiAuthBoundary:
    @staticmethod
    def _client(ctx):
        from fastapi.testclient import TestClient
        from research_engine.api.app import create_app
        return TestClient(create_app(ctx))

    def test_loopback_bind_needs_no_token(self, platform_ctx):
        """D-3 pinned: a loopback bind is a trusted boundary.

        This is a deliberate property, not an accident — it is pinned so it
        cannot drift silently in either direction.
        """
        platform_ctx.cfg.platform.api.host = "127.0.0.1"
        platform_ctx.cfg.platform.api.auth_token = ""
        client = self._client(platform_ctx)
        assert client.get("/projects").status_code == 200

    def test_external_bind_requires_token_on_the_request_path(self, platform_ctx):
        """A non-loopback bind must reject an unauthenticated request."""
        platform_ctx.cfg.platform.api.host = "0.0.0.0"
        platform_ctx.cfg.platform.api.auth_token = "correct-token"
        client = self._client(platform_ctx)
        assert client.get("/projects").status_code == 401
        assert client.get("/projects",
                          headers={"X-API-Token": "wrong"}).status_code == 401
        ok = client.get("/projects", headers={"X-API-Token": "correct-token"})
        assert ok.status_code == 200

    def test_only_provably_loopback_addresses_are_trusted(self):
        """A wildcard, a LAN address or a hostname is external.

        The predicate fails closed: anything that is not provably loopback
        requires a token. The exotic forms below are the ones a socket would
        still accept, so they must not slip through as loopback.
        """
        from research_engine.core.config import is_loopback_host
        # loopback
        assert is_loopback_host("127.0.0.1")
        assert is_loopback_host("::1")
        assert is_loopback_host("localhost")
        assert is_loopback_host("LOCALHOST")        # case-folded
        assert is_loopback_host("  127.0.0.1  ")   # whitespace
        assert is_loopback_host("[::1]")            # bracketed IPv6
        assert is_loopback_host("127.0.0.2")        # the whole 127/8 range
        # NOT loopback — every one of these would bind off-loopback or is an
        # exotic form we refuse to interpret (fail closed)
        assert not is_loopback_host("0.0.0.0")
        assert not is_loopback_host("::")
        assert not is_loopback_host("192.168.1.10")
        assert not is_loopback_host("example.internal")
        assert not is_loopback_host("169.254.169.254")   # link-local
        assert not is_loopback_host("::ffff:127.0.0.1")  # IPv4-mapped: over-strict, never a hole
        assert not is_loopback_host("2130706433")        # decimal IP form
        assert not is_loopback_host("0x7f000001")        # hex IP form
        assert not is_loopback_host("0")                 # inet_aton wildcard
        assert not is_loopback_host("")
        assert not is_loopback_host(None)                # type: ignore[arg-type]

    def test_app_without_an_explicit_context_still_enforces_the_token(self, tmp_path):
        """`create_app()` with no context must not disable the boundary.

        The dependency used to read the raw holder, which was still None when
        it ran — so an app created without an explicit context could NEVER
        require a token, whatever the configuration said. It now resolves the
        context the same way the routes do.
        """
        from research_engine.core.config import AppConfig
        from research_engine.services import context as ctx_mod
        from research_engine.api.app import create_app
        from fastapi.testclient import TestClient

        cfg = AppConfig.load()
        cfg.storage.data_dir = str(tmp_path)
        cfg.platform.api.host = "0.0.0.0"       # external
        cfg.platform.api.auth_token = "tok"
        ctx_mod.reset_context()
        ctx_mod.get_context(cfg=cfg)
        try:
            client = TestClient(create_app())     # no explicit context
            assert client.get("/projects").status_code == 401
            ok = client.get("/projects", headers={"X-API-Token": "tok"})
            assert ok.status_code == 200
        finally:
            ctx_mod.reset_context()

    def test_cli_host_override_is_the_address_the_app_authorises_on(self, tmp_path):
        """THE REGRESSION THIS INVARIANT EXISTS FOR.

        `--host 0.0.0.0` binds every interface while the configured host stays
        127.0.0.1. The app must authorise on the address that was actually
        bound — otherwise the whole API is served unauthenticated.
        """
        from research_engine.core.config import AppConfig
        from research_engine.services import context as ctx_mod
        import research_engine.cli.main as cli

        cfg = AppConfig.load()
        cfg.storage.data_dir = str(tmp_path)
        cfg.platform.api.host = "127.0.0.1"     # configured: loopback
        cfg.platform.api.auth_token = "tok"
        ctx_mod.reset_context()
        ctx_mod.get_context(cfg=cfg)
        try:
            captured = {}

            def fake_run(app, **kwargs):
                captured["app"] = app
                captured["kwargs"] = kwargs

            import uvicorn
            original_run = uvicorn.run
            uvicorn.run = fake_run
            try:
                ns = type("A", (), {"host": "0.0.0.0", "port": None})()
                cli.cmd_serve(ns)
            finally:
                uvicorn.run = original_run

            assert captured["kwargs"]["host"] == "0.0.0.0"
            from fastapi.testclient import TestClient
            client = TestClient(captured["app"])
            assert client.get("/projects").status_code == 401
            ok = client.get("/projects", headers={"X-API-Token": "tok"})
            assert ok.status_code == 200
        finally:
            ctx_mod.reset_context()

    def test_external_bind_without_token_is_refused_before_binding(self, tmp_path):
        """`cmd_serve` must refuse a non-loopback bind with no token, and it
        must refuse BEFORE anything binds."""
        from research_engine.core.config import AppConfig
        from research_engine.services import context as ctx_mod
        import research_engine.cli.main as cli

        cfg = AppConfig.load()
        cfg.storage.data_dir = str(tmp_path)
        cfg.platform.api.host = "127.0.0.1"
        cfg.platform.api.auth_token = ""
        ctx_mod.reset_context()
        ctx_mod.get_context(cfg=cfg)
        try:
            bound = []

            def fake_run(app, **kwargs):
                bound.append(kwargs)

            import uvicorn
            original_run = uvicorn.run
            uvicorn.run = fake_run
            try:
                ns = type("A", (), {"host": "0.0.0.0", "port": None})()
                with pytest.raises(SystemExit):
                    cli.cmd_serve(ns)
            finally:
                uvicorn.run = original_run
            assert not bound, "server bound despite the refusal"
        finally:
            ctx_mod.reset_context()
