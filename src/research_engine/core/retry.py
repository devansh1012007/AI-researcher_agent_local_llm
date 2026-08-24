"""Configurable retry policies for network / LLM / validation failures."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    backoff_base: float = 1.5  # seconds; delay = base ** attempt
    retry_on: tuple[type[BaseException], ...] = (Exception,)
    name: str = "generic"

    def delay_for(self, attempt: int) -> float:
        return min(30.0, self.backoff_base ** max(1, attempt))


NETWORK = RetryPolicy(name="network")
RATE_LIMIT = RetryPolicy(max_attempts=4, backoff_base=2.0, name="rate_limit")
LLM = RetryPolicy(max_attempts=2, backoff_base=2.0, name="llm")


def run_with_retries(fn: Callable[..., T], policy: RetryPolicy,
                     on_failure: str = "raise", default: Any = None,
                     is_retryable: Callable[[BaseException], bool] | None = None,
                     *args, **kwargs) -> T | Any:
    """Execute fn with retries. on_failure: raise|default. Records attempts."""
    last_exc: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except policy.retry_on as exc:
            if is_retryable and not is_retryable(exc):
                break
            last_exc = exc
            if attempt < policy.max_attempts:
                delay = policy.delay_for(attempt)
                log.warning("retry[%s] attempt %d/%d failed (%s); sleeping %.1fs",
                            policy.name, attempt, policy.max_attempts, exc, delay)
                time.sleep(delay)
    if on_failure == "raise" and last_exc is not None:
        raise last_exc
    return default
