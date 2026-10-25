"""Phase 3 tests: P2-3 silent exception handling, P2-4 assert removal, P2-5 money parser consolidation, P2-7 health events."""
from __future__ import annotations

import ast
from pathlib import Path
import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_no_production_assert_statements_in_src():
    """P2-4: production modules under src/research_engine must not use assert for runtime checks."""
    src_root = ROOT / "src" / "research_engine"
    offenders = []
    for py in sorted(src_root.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                offenders.append(f"{py.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, f"Found assert statements in production code: {offenders}"


def test_health_report_surfaces_dropped_events_and_persistence_errors(platform_ctx):
    """P2-7: health_report includes events check and degrades when events drop or fail."""
    from research_engine.api.app import health_report
    from research_engine.platform.events import DomainEvent

    h0 = health_report(platform_ctx)
    assert "events" in h0["checks"]
    assert h0["checks"]["events"]["level"] == "healthy"

    # Simulate a persistence failure on EventPersister
    platform_ctx._persister.persistence_errors = 2
    h1 = health_report(platform_ctx)
    assert h1["checks"]["events"]["level"] == "degraded"
    assert h1["checks"]["events"]["persistence_errors"] == 2
    assert h1["status"] == "degraded"
    platform_ctx._persister.persistence_errors = 0


def test_event_persister_counts_errors_without_raising():
    """P2-3: EventPersister increments persistence_errors when platform_db.record_event fails."""
    from research_engine.platform.events import DomainEvent, EventBus, EventPersister

    class _BrokenDB:
        def persist_event(self, *args, **kwargs):
            raise RuntimeError("disk full")

    bus = EventBus()
    persister = EventPersister(_BrokenDB(), bus)
    bus.publish(DomainEvent("TestEvent", project_id="proj_1"))
    persister.stop()
    assert persister.persistence_errors == 1


def test_canonical_money_helpers_shared_across_policies_competitors_and_market():
    """P2-5: policies.py owns canonical money helpers used by competitors.py and market.py."""
    from research_engine.specialists.startup.policies import (
        _AMOUNT_RE, currency_of, is_magnitude_price, money_snippet, parse_money,
    )
    from research_engine.specialists.startup.competitors import (
        _AMOUNT_RE as comp_amount_re, _is_magnitude_price as comp_is_mag,
    )
    from research_engine.specialists.startup.market import MarketAnalyzer

    assert comp_amount_re is _AMOUNT_RE
    assert comp_is_mag is is_magnitude_price

    claim = "The global market size for retail bookkeeping software reached $4.5 billion in 2025."
    assert MarketAnalyzer._parse_value(claim) == parse_money(claim)[0] == 4.5e9
    assert MarketAnalyzer._currency_of(claim) == currency_of(claim) == "USD"
    assert "$4.5 billion" in MarketAnalyzer._size_snippet(claim)
