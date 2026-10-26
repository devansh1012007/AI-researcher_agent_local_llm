"""Provider resilience: circuit breakers, rate limits, failover (spec #53-56).

CircuitBreaker: after N consecutive failures a provider trips OPEN; calls
fail fast to the fallback until the cooldown elapses, then HALF_OPEN probes
with one request. Prevents hammering broken services.

RateLimiter: token bucket per provider/domain/task-type with configurable
rates. Non-blocking acquire (wait=False) so callers can degrade instead of
stalling research.

FailoverRegistry: wraps ProviderRegistry with ordered primary->fallback
chains from configuration.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


class CircuitBreaker:
    CLOSED, OPEN, HALF_OPEN = "CLOSED", "OPEN", "HALF_OPEN"

    def __init__(self, failure_threshold: int = 4,
                 cooldown_seconds: float = 60.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._state = self.CLOSED
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == self.OPEN and \
               time.monotonic() - self._opened_at >= self.cooldown_seconds:
                self._state = self.HALF_OPEN
            return self._state

    def allow(self) -> bool:
        st = self.state
        return st in (self.CLOSED, self.HALF_OPEN)

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._state = self.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            if self._state == self.HALF_OPEN:
                self._trip()
                return
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.failure_threshold:
                self._trip()

    def _trip(self) -> None:
        self._state = self.OPEN
        self._opened_at = time.monotonic()


class TokenBucketRateLimiter:
    """rate = tokens/second sustained, burst = bucket capacity."""

    def __init__(self, rate_per_sec: float, burst: int):
        self.rate = rate_per_sec
        self.burst = burst
        self._tokens = float(burst)
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, wait: bool = False, timeout: float = 10.0) -> bool:
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(float(self.burst),
                                   self._tokens + (now - self._updated) * self.rate)
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
                need = (1.0 - self._tokens) / self.rate
            if not wait or need > timeout:
                return False
            time.sleep(min(need, 0.5))


class DomainRateLimits:
    """Per-domain + per-provider limit table with sane defaults (#55)."""

    DEFAULTS = {"*": (5.0, 10)}   # 5 req/s sustained, burst 10

    def __init__(self, overrides: dict[str, tuple[float, int]] | None = None):
        self._limits: dict[str, TokenBucketRateLimiter] = {}
        self._rules = {**(overrides or {})}
        self._lock = threading.Lock()
        for key, (rate, burst) in {**self.DEFAULTS, **self._rules}.items():
            self._limits[key] = TokenBucketRateLimiter(rate, burst)

    def acquire(self, provider: str, domain: str = "",
                wait: bool = True) -> bool:
        limiter = self._limits.get(domain) or self._limits.get(provider) \
            or self._limits["*"]
        return limiter.acquire(wait=wait)


@dataclass
class FailoverChain:
    primary: str
    fallbacks: list[str] = field(default_factory=list)
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)


class FailoverExecutor:
    """Runs an operation against an ordered provider list, honoring breakers
    and rate limits; records outcomes back into the breaker (#53/#54)."""

    def __init__(self, rate_limits: DomainRateLimits | None = None):
        self.breakers: dict[str, CircuitBreaker] = {}
        self.limits = rate_limits or DomainRateLimits()

    def breaker_for(self, name: str) -> CircuitBreaker:
        if name not in self.breakers:
            self.breakers[name] = CircuitBreaker()
        return self.breakers[name]

    def run(self, chain: list[str], op, *, domain: str = "",
            wait_rate: bool = True):
        """op(provider_name) -> value. Raises last error if all fail."""
        errors: list[str] = []
        for name in chain:
            br = self.breaker_for(name)
            if not br.allow():
                continue   # tripped — skip silently toward fallback
            if not self.limits.acquire(name, domain=domain, wait=wait_rate):
                errors.append(f"{name}: rate limited")
                continue
            try:
                result = op(name)
                br.record_success()
                return result
            except Exception as exc:  # noqa: BLE001 — failover boundary
                br.record_failure()
                errors.append(f"{name}: {exc}")
        raise RuntimeError("all providers failed: " + "; ".join(errors[-3:]))
