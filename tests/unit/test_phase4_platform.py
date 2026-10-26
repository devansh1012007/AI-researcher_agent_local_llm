"""Phase 4 platform primitives: errors, metrics, events, redaction,
permissions, path sandbox, backup/restore, resilience (spec #46-66)."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from research_engine.platform.errors import (
    ClassifiedError, ErrorCategory, backoff_delay, classify, run_with_retries,
)
from research_engine.platform.events import DomainEvent, EventBus
from research_engine.platform.metrics import MetricsRegistry, sample_resources
from research_engine.platform.obs_logging import (
    IncidentLog, StructuredLogger, redact,
)
from research_engine.platform.resilience import (
    CircuitBreaker, DomainRateLimits, FailoverExecutor, TokenBucketRateLimiter,
)
from research_engine.security.permissions import (
    Permission, PermissionDeniedError, PermissionEngine, PathSandbox,
)


# ------------------------------------------------------------- errors #123
class TestErrorClassification:
    def test_rate_limit_detected(self):
        assert classify(message="HTTP 429 too many requests") is ErrorCategory.RATE_LIMIT

    def test_auth_not_retried(self):
        assert classify(message="401 unauthorized") is ErrorCategory.AUTH
        pol = __import__("research_engine.platform.errors",
                         fromlist=["DEFAULT_POLICIES"]).DEFAULT_POLICIES[
            ErrorCategory.AUTH]
        assert pol.retryable is False

    def test_network_transient(self):
        assert classify(message="connection reset by peer") is ErrorCategory.NETWORK
        assert classify(message="getaddrinfo failed") is ErrorCategory.NETWORK

    def test_db_lock(self):
        assert classify(message="database is locked") is ErrorCategory.DATABASE

    def test_schema_vs_parsing(self):
        assert classify(exc=ValueError("bad json")) in (
            ErrorCategory.SCHEMA, ErrorCategory.UNKNOWN)

    def test_backoff_grows_with_jitter(self):
        d1 = backoff_delay(__import__("research_engine.platform.errors",
                                      fromlist=["RetryPolicy"]).RetryPolicy(
                                          3, 1.0), 1)
        d3 = backoff_delay(__import__("research_engine.platform.errors",
                                      fromlist=["RetryPolicy"]).RetryPolicy(
                                          3, 1.0), 3)
        assert d3 >= d1 * 1.5

    def test_run_with_retries_succeeds_then_raises_classified(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("timed out")
            return "ok"

        from research_engine.platform.errors import RetryPolicy
        out = run_with_retries(flaky, what="fetch", sleep=lambda s: None,
                               policy=RetryPolicy(3, 0.0))
        assert out == "ok" and calls["n"] == 3

        def always():
            raise RuntimeError("nope")

        with pytest.raises(ClassifiedError):
            run_with_retries(always, what="x", sleep=lambda s: None)


# ------------------------------------------------------------ metrics #48
class TestMetrics:
    def test_counters_gauges_histograms(self):
        m = MetricsRegistry()
        m.incr("llm_calls", provider="mock")
        m.incr("llm_calls", provider="mock")
        m.gauge("ram_used_pct", 42.5)
        for v in (10, 20, 30, 40):
            m.observe("latency_ms", v)
        snap = m.snapshot()
        assert snap["counters"]["llm_calls{provider=mock}"] == 2
        assert snap["gauges"]["ram_used_pct"] == 42.5
        h = snap["histograms"]["latency_ms"]
        assert h["count"] == 4 and h["p50"] == 30 or h["p50"] == 20

    def test_thread_safety(self):
        m = MetricsRegistry()
        def hammer():
            for _ in range(500):
                m.incr("c")
        ts = [threading.Thread(target=hammer) for _ in range(4)]
        [t.start() for t in ts]; [t.join() for t in ts]
        assert m.snapshot()["counters"]["c"] == 2000

    def test_resource_sampling_graceful(self):
        res = sample_resources()
        assert isinstance(res, dict)   # {} on non-linux; mem/load on linux


# ------------------------------------------------------------- events #21-22
class TestEventBus:
    def test_pubsub_and_filtering(self):
        bus = EventBus()
        _sid, q_all = bus.subscribe(None)
        _sid2, q_ev = bus.subscribe(["ResearchCompleted"])
        bus.publish(DomainEvent(type="EvidenceCreated", project_id="p"))
        ev = q_all.get(timeout=1)
        assert ev.type == "EvidenceCreated"
        assert q_ev.empty()

        bus.publish(DomainEvent(type="ResearchCompleted", project_id="p"))
        assert q_ev.get(timeout=1).type == "ResearchCompleted"

    def test_slow_consumer_does_not_block(self):
        bus = EventBus(queue_size=2)
        _sid, q = bus.subscribe(None)
        for i in range(10):
            bus.publish(DomainEvent(type=f"E{i}"))
        assert q.qsize() <= 2  # oldest dropped, publisher never blocked


# ------------------------------------------------------------ logging #47/#66
class TestStructuredLogging:
    def test_record_fields_and_redaction(self, tmp_path):
        lg = StructuredLogger(tmp_path / "log.jsonl")
        rec = lg.info("llm_call", project_id="p1", job_id="j1",
                      trace_id="trc_abc", error="api_key=sk-1234567890abcdef")
        for k in ("ts", "level", "event", "project_id", "job_id", "trace_id",
                  "duration_ms", "status", "error"):
            assert k in rec
        line = (tmp_path / "log.jsonl").read_text().strip()
        assert "sk-1234567890" not in line
        assert "<redacted>" in line or "api_key=" not in json.loads(line)["error"]

    def test_redact_patterns(self):
        assert "sk-" not in redact("bearer Bearer abc.def and sk-abcdefghij")
        assert "<redacted>" in redact("password=hunter2")

    def test_metadata_deep_redaction(self, tmp_path):
        lg = StructuredLogger(tmp_path / "log.jsonl")
        rec = lg.info("e", metadata={"api_token": "secret-value", "safe": 1})
        assert rec["metadata"]["api_token"] == "<redacted>"
        assert rec["metadata"]["safe"] == 1

    def test_incident_log(self, tmp_path):
        IncidentLog(tmp_path).record("j1", "retrieval", "timeout spike",
                                     "provider outage", "failover engaged")
        text = (tmp_path / "_global" / "incidents.md").read_text()
        assert "retrieval" in text and "outage" in text


# --------------------------------------------------------- permissions #33/#64
class TestPermissions:
    def test_default_read_only(self):
        eng = PermissionEngine()
        eng.require(Permission.READ, "get_status")
        with pytest.raises(PermissionDeniedError):
            eng.require(Permission.RESEARCH, "start_research")

    def test_higher_implies_lower_never_reverse(self):
        eng = PermissionEngine({Permission.RESEARCH})
        eng.require(Permission.READ, "r")
        eng.require(Permission.RESEARCH, "s")
        with pytest.raises(PermissionDeniedError):
            eng.require(Permission.WRITE, "w")

    def test_admin_all(self):
        PermissionEngine({Permission.ADMIN}).require(
            Permission.EXECUTE_EXPERIMENT, "x")

    def test_path_sandbox_blocks_escape(self, tmp_path):
        sb = PathSandbox([tmp_path / "data"])
        inside = sb.validate_read(str(tmp_path / "data" / "proj_1" / "db.sqlite"))
        assert str(inside).startswith(str(tmp_path))
        with pytest.raises(PermissionError):
            sb.validate_write("/etc/passwd")
        with pytest.raises(PermissionError):
            sb.validate_read(str(Path.home() / ".ssh" / "id_rsa"))


# ---------------------------------------------------------- resilience #53-56
class TestResilience:
    def test_circuit_breaker_trips_and_recovers(self):
        br = CircuitBreaker(failure_threshold=3, cooldown_seconds=0.05)
        for _ in range(3):
            br.record_failure()
        assert br.state == CircuitBreaker.OPEN
        assert not br.allow()
        time.sleep(0.06)
        assert br.state == CircuitBreaker.HALF_OPEN
        br.record_success()
        assert br.state == CircuitBreaker.CLOSED

    def test_failover_falls_back(self):
        fx = FailoverExecutor()

        def op(name):
            if name == "primary":
                raise RuntimeError("down")
            return f"ok:{name}"

        assert fx.run(["primary", "secondary"], op) == "ok:secondary"
        # after threshold, primary skipped entirely
        for _ in range(4):
            try:
                fx.run(["primary", "secondary"], op)
            except RuntimeError:
                pass
        assert fx.breaker_for("primary").state == CircuitBreaker.OPEN

    def test_rate_limiter_burst(self):
        rl = TokenBucketRateLimiter(rate_per_sec=1000, burst=3)
        got = sum(rl.acquire(wait=False) for _ in range(10))
        assert got == 3

    def test_domain_limits(self):
        dl = DomainRateLimits({"arxiv": (0.01, 1)})
        assert dl.acquire("arxiv", wait=False)
        assert not dl.acquire("arxiv", wait=False)
