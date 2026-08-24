"""Synthesis worker: LLM writes report sections from STRUCTURED context.

The synthesizer receives evidence-backed findings, contradictions, gaps and source
metadata — never a giant raw dump. If no model is available, deterministic
fallback sections are generated directly from stored state.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from research_engine.prompts.registry import get_prompt
from research_engine.providers.llm.base import LLMProvider

log = logging.getLogger(__name__)


class SectionOutput(BaseModel):
    markdown: str = ""


class Synthesizer:
    def __init__(self, provider: LLMProvider | None):
        self.provider = provider

    def write_section(self, section: str, ctx: dict) -> str | None:
        """Returns markdown or None if no provider / failure (caller falls back)."""
        if self.provider is None:
            return None
        spec = get_prompt("synthesizer")
        user = spec.render(section=section,
                           objective=ctx.get("objective", ""),
                           research_question=ctx.get("research_question", ""),
                           scope_and_assumptions=ctx.get("scope_and_assumptions", "(none recorded)"),
                           findings_input=ctx.get("findings_input", "(no evidence collected)"),
                           contradictions_input=ctx.get("contradictions_input", "(none)"),
                           gaps_input=ctx.get("gaps_input", "(none)"),
                           source_summary=ctx.get("source_summary", ""))
        out, errors = self.provider.structured(spec.system, user, SectionOutput, max_attempts=2)
        if out is None or not out.markdown.strip():
            log.warning("synthesis of section %r failed: %s", section, errors[-1:])
            return None
        return out.markdown


def build_findings_context(claims: list, evidence_by_id: dict, max_claims: int = 60) -> str:
    """Deterministic structured context: claim -> supporting evidence with IDs."""
    lines = []
    for c in sorted(claims, key=lambda x: -x.confidence)[:max_claims]:
        ev_lines = []
        for eid in c.supported_by[:4]:
            e = evidence_by_id.get(eid)
            if e is None or e.status.value == "REJECTED":
                continue
            loc = f" ({e.location})" if e.location else ""
            ev_lines.append(f"  - [{e.id}] \"{e.quote[:180]}\" — {e.source_title[:80]} "
                            f"(tier {e.source_tier}){loc}")
        lines.append(f"* {c.text} [{c.kind.value}, confidence={c.confidence:.2f}]"
                     f"{chr(10)}{chr(10).join(ev_lines) if ev_lines else '  (supporting evidence missing)'}")
    return "\n".join(lines) or "(no claims)"


def deterministic_findings(claims: list, evidence_by_id: dict) -> str:
    """Fallback section body when no synthesis model is available."""
    parts = ["### Findings assembled deterministically from stored evidence\n"]
    facts = [c for c in claims if c.kind.value == "FACT" and c.supported_by]
    inferences = [c for c in claims if c.kind.value == "INFERENCE"]
    assumptions = [c for c in claims if c.kind.value == "ASSUMPTION"]

    def block(title, items):
        if not items:
            return ""
        out = [f"\n#### {title}\n"]
        for c in items[:40]:
            srcs = []
            for eid in c.supported_by[:3]:
                e = evidence_by_id.get(eid)
                if e:
                    srcs.append(f"[{e.id}]({e.source_url}) tier:{e.source_tier}")
            out.append(f"- **{c.text}** (confidence {c.confidence:.2f}) — sources: "
                       + ("; ".join(srcs) or "n/a"))
        return "\n".join(out) + "\n"

    parts.append(block("Evidence-backed findings", facts))
    parts.append(block("Inferences", inferences))
    parts.append(block("Assumptions", assumptions))
    return "\n".join(parts)
