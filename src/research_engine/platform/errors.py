"""Error classification + retry policy mapping (spec #123/#56).

Every recoverable failure gets a category; each category carries its own
retry behavior. Retrying a 4xx the way we retry a timeout is how you get
banned by every provider on the internet.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from enum import Enum


class ErrorCategory(str, Enum):
    NETWORK = "NETWORK"
    AUTH = "AUTH"
    RATE_LIMIT = "RATE_LIMIT"
    PARSING = "PARSING"
    SCHEMA = "SCHEMA"
    MODEL = "MODEL"
    DATABASE = "DATABASE"
    RESOURCE = "RESOURCE"
    SECURITY = "SECURITY"
    USER = "USER"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    backoff_base: float          # seconds
    backoff_cap: float = 60.0
    jitter: bool = True
    retryable: bool = True


# category -> default retry behavior (spec #56: do not retry every failure)
DEFAULT_POLICIES: dict[ErrorCategory, RetryPolicy] = {
    # transient — worth retrying with backoff
    ErrorCategory.NETWORK: RetryPolicy(3, 1.5),
    ErrorCategory.RATE_LIMIT: RetryPolicy(4, 4.0, backoff_cap=90.0),
    ErrorCategory.MODEL: RetryPolicy(2, 2.0),          # provider hiccup / empty output
    ErrorCategory.DATABASE: RetryPolicy(5, 0.4, backoff_cap=8.0),  # lock contention
    ErrorCategory.RESOURCE: RetryPolicy(2, 5.0),
    # not transient — fail fast into dead-letter / skip
    ErrorCategory.AUTH: RetryPolicy(1, 0.0, retryable=False),
    ErrorCategory.PARSING: RetryPolicy(1, 0.0, retryable=False),
    ErrorCategory.SCHEMA: RetryPolicy(1, 0.0, retryable=False),
    ErrorCategory.SECURITY: RetryPolicy(1, 0.0, retryable=False),
    ErrorCategory.USER: RetryPolicy(1, 0.0, retryable=False),
    ErrorCategory.UNKNOWN: RetryPolicy(2, 1.0),
}


class ClassifiedError(Exception):
    """An exception carrying its classification so callers don't guess."""

    def __init__(self, category: ErrorCategory, message: str,
                 cause: BaseException | None = None):
        super().__init__(message)
        self.category = category
        self.cause = cause


_STATUS_MAP = {
    401: ErrorCategory.AUTH, 403: ErrorCategory.AUTH,
    429: ErrorCategory.RATE_LIMIT,
}

# substring fingerprints for common failure shapes (checked in order)
_FINGERPRINTS: list[tuple[str, ErrorCategory]] = [
    ("rate limit", ErrorCategory.RATE_LIMIT),
    ("too many requests", ErrorCategory.RATE_LIMIT),
    ("timed out", ErrorCategory.NETWORK),
    ("timeout", ErrorCategory.NETWORK),
    ("connection", ErrorCategory.NETWORK),
    ("getaddrinfo", ErrorCategory.NETWORK),       # DNS
    ("ssl", ErrorCategory.NETWORK),
    ("remote protocol error", ErrorCategory.NETWORK),
    ("unauthorized", ErrorCategory.AUTH),
    ("forbidden", ErrorCategory.AUTH),
    ("api key", ErrorCategory.AUTH),
    ("database is locked", ErrorCategory.DATABASE),
    ("disk full", ErrorCategory.RESOURCE),
    ("no space left", ErrorCategory.RESOURCE),
    ("cannot allocate memory", ErrorCategory.RESOURCE),
    ("permission denied", ErrorCategory.SECURITY),
]


def classify(exc: BaseException | None = None, message: str = "") -> ErrorCategory:
    """Best-effort classification of an exception or error text."""
    if isinstance(exc, ClassifiedError):
        return exc.category
    if isinstance(exc, json_schema_error_types()):
        return ErrorCategory.SCHEMA
    text = (message or str(exc or "")).lower()
    status = _extract_http_status(text)
    if status in _STATUS_MAP:
        return _STATUS_MAP[status]
    for needle, cat in _FINGERPRINTS:
        if needle in text:
            return cat
    return ErrorCategory.UNKNOWN


def json_schema_error_types() -> tuple[type, ...]:
    import json
    return (json.JSONDecodeError, ValueError)


def _extract_http_status(text: str) -> int | None:
    import re
    m = re.search(r"(?:status|code)[= :]*(\d{3})", text) or \
        re.search(r"\b(4\d\d|5\d\d)\b(?:\s|$|,)", text)
    if m:
        try:
            code = int(m.group(1))
            if code in (401, 403, 429) or 500 <= code < 600:
                return code
            if 400 <= code < 500:
                return 400  # generic client error -> non-retryable family
        except ValueError:
            pass
    return None


def backoff_delay(policy: RetryPolicy, attempt: int) -> float:
    """Exponential backoff with jitter (attempt is 1-based)."""
    delay = min(policy.backoff_cap, policy.backoff_base * (2 ** (attempt - 1)))
    if policy.jitter:
        delay *= 0.5 + random.random()
    return delay


def run_with_retries(fn, *, what: str, policy: RetryPolicy | None = None,
                     sleep=time.sleep, on_retry=None):
    """Execute fn() honoring classification-aware retries.

    Raises ClassifiedError-wrapped exception after exhausting attempts.
    """
    pol = policy or DEFAULT_POLICIES[ErrorCategory.UNKNOWN]
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except Exception as exc:
            cat = classify(exc)
            pol = pol if pol.max_attempts > 1 else DEFAULT_POLICIES[cat]
            if not pol.retryable or attempt >= pol.max_attempts:
                raise ClassifiedError(cat, f"{what}: {exc}", cause=exc) from exc
            delay = backoff_delay(pol, attempt)
            if on_retry:
                on_retry(attempt, cat, delay)
            sleep(delay)
