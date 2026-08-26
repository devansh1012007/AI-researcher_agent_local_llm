"""LLM call telemetry (Phase 6 §24-§25).

One choke point: ModelRouter hands out instrumented providers, so every
production LLM call observes (provider, model, role, ok, latency,
schema_failures) into an injectable sink. Telemetry NEVER breaks research —
sink failures are swallowed by contract. Direct-injected fakes (ScriptedLLM)
bypass this by design so offline tests stay hermetic.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

log = logging.getLogger(__name__)

# Signature: (provider, model, role, ok: bool, latency_s: float,
#             schema_failures: int) -> None
Sink = Callable[..., None]
_sink: Sink | None = None


def install_sink(fn: Sink | None) -> None:
    global _sink
    _sink = fn


def record(provider: str, model: str, role: str, ok: bool, latency_s: float,
           schema_failures: int = 0) -> None:
    if _sink is None:
        return
    try:
        _sink(provider, model, role, bool(ok), float(latency_s),
              int(schema_failures))
    except Exception:       # noqa: BLE001 — observability must be inert
        log.debug("llm telemetry sink failed", exc_info=True)


class InstrumentedProvider:
    """Transparent wrapper adding per-call telemetry to a role-bound
    provider. Delegation keeps the inner provider's `.calls` counter (used
    by orchestrator metrics) fully intact."""

    def __init__(self, inner, role: str, provider_name: str, model: str):
        self._inner = inner
        self._role = role
        self._provider_name = provider_name
        self._model = model

    def complete(self, system: str, user: str) -> str:
        t0 = time.perf_counter()
        try:
            out = self._inner.complete(system, user)
        except Exception:
            record(self._provider_name, self._model, self._role,
                   ok=False, latency_s=time.perf_counter() - t0)
            raise
        record(self._provider_name, self._model, self._role, ok=True,
               latency_s=time.perf_counter() - t0)
        return out

    def structured(self, system: str, user: str, schema,
                   max_attempts: int = 3):
        t0 = time.perf_counter()
        out, errs = self._inner.structured(system, user, schema, max_attempts)
        record(self._provider_name, self._model, self._role,
               ok=out is not None, latency_s=time.perf_counter() - t0,
               schema_failures=max(0, len(errs)))
        return out, errs

    def __getattr__(self, name):        # delegate everything else
        return getattr(self._inner, name)


class RoutingInfo:
    """What model policy needs to know about one resolved role."""
    __slots__ = ("provider", "model", "role")

    def __init__(self, provider: str, model: str, role: str):
        self.provider = provider
        self.model = model
        self.role = role


def wrap_for_telemetry(inner, role: str, cfg) -> InstrumentedProvider:
    return InstrumentedProvider(inner, role, cfg.provider, cfg.model)
