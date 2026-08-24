"""LLM provider abstraction.

LLMs may propose decisions; they never own persistence or control flow.
Structured outputs are always parsed -> validated -> repaired -> fallback.
"""
from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from research_engine.core.config import LLMRoleConfig

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    pass


class LLMProvider(ABC):
    def __init__(self, cfg: LLMRoleConfig):
        self.cfg = cfg
        self.calls = 0

    @abstractmethod
    def _raw_complete(self, system: str, user: str) -> str:
        ...

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return self._raw_complete(system, user)

    # -- structured output -------------------------------------------------
    def structured(self, system: str, user: str, schema: type[T],
                   max_attempts: int = 3) -> tuple[T | None, list[str]]:
        """Return (validated_model|None, errors). Never raises on bad output."""
        errors: list[str] = []
        prompt = user
        for attempt in range(1, max_attempts + 1):
            raw = self.complete(system, prompt)
            obj = extract_json(raw)
            if obj is None:
                errors.append(f"attempt {attempt}: no JSON found")
            else:
                try:
                    return schema.model_validate(obj), errors
                except ValidationError as exc:
                    errors.append(f"attempt {attempt}: validation failed: {exc.errors()[:3]}")
            prompt = (
                f"{user}\n\nYour previous response was invalid: {errors[-1]}\n"
                f"Respond again with ONLY valid JSON matching this schema:\n"
                f"{json.dumps(_schema_hint(schema))}"
            )
        log.error("structured output failed after %d attempts: %s", max_attempts, errors)
        return None, errors


def _schema_hint(model: type[BaseModel]) -> dict:
    props = {}
    for name, field in model.model_fields.items():
        t = str(field.annotation)
        props[name] = t
    return {"type": "object", "properties": props}


def extract_json(text: str) -> dict | list | None:
    """Extract first JSON object/array from LLM text. Handles ```json fences."""
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass
    # find balanced braces / brackets
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    return None


class MockProvider(LLMProvider):
    """Deterministic fake provider for offline tests.

    Behavior is driven by an optional handler: fn(system, user) -> str.
    Default returns a minimal JSON object so structured() fails validation gracefully.
    """

    def __init__(self, cfg: LLMRoleConfig | None = None, handler=None):
        super().__init__(cfg or LLMRoleConfig(provider="mock", model="mock-model"))
        self.handler = handler

    def _raw_complete(self, system: str, user: str) -> str:
        if self.handler:
            return self.handler(system, user)
        return "{}"
