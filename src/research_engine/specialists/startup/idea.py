"""Idea card and verdict policy for the ``startup_validation`` engine.

The engine evaluates ONE stated idea. The idea arrives as plain text (the project
question): line 1 is the idea, later lines are ``key: value`` fields. The label
set doubles as the engine's ``clarifier.required_inputs`` so a field that is
already written in the card is never asked again.

Policy lives here, in one place (AGENTS.md: no duplicated policy):

* the verdict is derived from the existing specialist outputs (quality gate,
  readiness, recommendation) plus two guards that only an idea evaluation needs:
  an undefined customer or problem, and a falsified critical assumption;
* desk research alone can never produce a "this will work" verdict, and absence
  of evidence is never reported as refutation.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

CARD_KEYS: tuple[str, ...] = (
    "problem",
    "customer_segment",
    "alternative",
    "price_point",
    "riskiest_assumption",
    "geography",
    "existing_traction",
    "founder_constraints",
)
ESSENTIAL_KEYS: tuple[str, ...] = ("problem", "customer_segment")

_ALIASES: dict[str, str] = {
    "customer": "customer_segment",
    "segment": "customer_segment",
    "target_customer": "customer_segment",
    "who": "customer_segment",
    "competitor": "alternative",
    "competitors": "alternative",
    "alternatives": "alternative",
    "workaround": "alternative",
    "current_solution": "alternative",
    "price": "price_point",
    "pricing": "price_point",
    "assumption": "riskiest_assumption",
    "risk": "riskiest_assumption",
    "country": "geography",
    "region": "geography",
    "location": "geography",
    "traction": "existing_traction",
    "founder": "founder_constraints",
    "constraints": "founder_constraints",
    "pain": "problem",
    "idea": "idea",
}
_KNOWN = set(CARD_KEYS) | {"idea"}
_LABEL_RE = re.compile(r"^\s*([A-Za-z][A-Za-z _-]{1,30}?)\s*[:=]\s*(.*)$")
_IDEA_PREFIX_RE = re.compile(r"^\s*evaluate\s+(?:this\s+)?startup\s+idea\s*[:\-]?\s*", re.I)
_ASKED_KEY_RE = re.compile(r"specify\s+([a-z_]+)\s+for this research project", re.I)

# Positive verdicts are deliberately few: only VALIDATE_NEXT says "spend real effort".
VERDICTS: dict[str, str] = {
    "DEFINE_THE_IDEA": "The idea is not specific enough to evaluate: define the customer and the problem first.",
    "NOT_ENOUGH_EVIDENCE": "No evidence tied to the stated problem was found. This is not a refutation.",
    "RESEARCH_MORE": "Coverage gaps still block a decision. More desk research is cheap and useful.",
    "VALIDATE_NEXT": "Desk evidence justifies a real-world test. It does not mean the idea will work.",
    "REFINE_THE_IDEA": "The strongest counterevidence points at a specific weakness. Reshape the idea around it.",
    "COMPARE_ALTERNATIVES": "Evidence is inconclusive. Compare against alternative ideas before investing effort.",
    "STOP_OR_PIVOT": "A completed test falsified a critical assumption.",
}
POSITIVE_VERDICTS = frozenset({"VALIDATE_NEXT"})
# Quality-gate checks that must hold before VALIDATE_NEXT may be reported.
POSITIVE_VERDICT_REQUIRES = ("counterevidence_searched", "competition_researched")

_DECISION_TO_VERDICT = {
    "start_validating": "VALIDATE_NEXT",
    "continue_researching": "RESEARCH_MORE",
    "modify": "REFINE_THE_IDEA",
    "compare": "COMPARE_ALTERNATIVES",
    "abandon": "STOP_OR_PIVOT",
}

# Assumption status vocabularies are not consistent in the codebase
# (models/reasoning.py: validated/invalidated; older code: verified/falsified).
VALIDATED_STATUSES = ("validated", "verified")
FALSIFIED_STATUSES = ("invalidated", "falsified")


@dataclass
class IdeaCard:
    idea: str = ""
    problem: str = ""
    customer_segment: str = ""
    alternative: str = ""
    price_point: str = ""
    riskiest_assumption: str = ""
    geography: str = ""
    existing_traction: str = ""
    founder_constraints: str = ""
    sources: dict[str, str] = field(default_factory=dict)  # key -> "card" | "answer"

    def missing_essential(self) -> list[str]:
        return [k for k in ESSENTIAL_KEYS if not getattr(self, k).strip()]

    def missing_optional(self) -> list[str]:
        return [k for k in CARD_KEYS if k not in ESSENTIAL_KEYS and not getattr(self, k).strip()]

    def text_for_matching(self) -> str:
        """Text used to link gathered evidence to THIS idea (not to the whole market)."""
        return " ".join([self.idea, self.problem, self.customer_segment, self.alternative])

    def to_dict(self) -> dict:
        return asdict(self)


def _normalise_key(raw: str) -> str:
    key = re.sub(r"[\s-]+", "_", raw.strip().lower())
    return _ALIASES.get(key, key)


def parse_idea_card(text: str) -> IdeaCard:
    """Parse the project question into an IdeaCard. Never raises; never invents a field."""
    card = IdeaCard()
    current: str | None = None
    free: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            current = None
            continue
        m = _LABEL_RE.match(line)
        if m:
            key = _normalise_key(m.group(1))
            if key in _KNOWN:
                current = key
                value = m.group(2).strip()
                setattr(card, key, (getattr(card, key) + " " + value).strip())
                card.sources[key] = "card"
                continue
        if current is not None:  # continuation of the previous labelled field
            setattr(card, current, (getattr(card, current) + " " + line.strip()).strip())
        else:
            free.append(line.strip())
    if not card.idea:
        card.idea = _IDEA_PREFIX_RE.sub("", " ".join(free)).strip()
        if card.idea:
            card.sources["idea"] = "card"
    else:
        card.idea = _IDEA_PREFIX_RE.sub("", card.idea).strip()
    return card


def answers_from_questions(questions) -> dict[str, str]:
    """Map ANSWERED required-input questions back to idea card keys."""
    out: dict[str, str] = {}
    for q in questions or []:
        if getattr(q, "status", "") != "ANSWERED" or not (getattr(q, "answer", "") or "").strip():
            continue
        m = _ASKED_KEY_RE.search(getattr(q, "text", "") or "")
        if not m:
            continue
        key = _normalise_key(m.group(1))
        if key in CARD_KEYS:
            out[key] = q.answer.strip()
    return out


def merge_answers(card: IdeaCard, answers: dict[str, str]) -> IdeaCard:
    """An explicit later answer overrides the card text for that field."""
    for key, value in answers.items():
        if key in CARD_KEYS and value.strip():
            setattr(card, key, value.strip())
            card.sources[key] = "answer"
    return card


def build_idea_question(idea: str, **fields: str) -> str:
    """Canonical question text for ``research new --engine startup_validation``."""
    idea = (idea or "").strip()
    if not idea:
        raise ValueError("idea must not be empty")
    lines = [f"Evaluate startup idea: {idea}"]
    for key in CARD_KEYS:
        value = (fields.get(key) or "").strip()
        if value:
            lines.append(f"{key}: {' '.join(value.split())}")
    unknown = set(fields) - set(CARD_KEYS)
    if unknown:
        raise ValueError(f"unknown idea card field(s): {sorted(unknown)}; allowed: {list(CARD_KEYS)}")
    return "\n".join(lines)


_FOUNDER_SUBKEYS = {
    "skills": "skills", "skill": "skills",
    "capital": "capital", "budget": "capital",
    "time": "time_available", "time_available": "time_available",
    "geography": "geography",
    "network": "network",
    "technical": "technical_capabilities", "technical_capabilities": "technical_capabilities",
    "industry": "industry_access", "industry_access": "industry_access",
    "risk": "risk_preference", "risk_preference": "risk_preference",
}
_LIST_FIELDS = {"skills", "network", "technical_capabilities", "industry_access"}


def founder_fields(text: str) -> dict:
    """Parse ``skills=a,b; capital=...; time=...`` into FounderProfile fields.

    Returns {} when no recognised sub-label is present: free text is never guessed
    into structured fields.
    """
    out: dict = {}
    for part in re.split(r"[;\n]", text or ""):
        m = re.match(r"^\s*([A-Za-z_ ]+?)\s*[=:]\s*(.+?)\s*$", part)
        if not m:
            continue
        key = _FOUNDER_SUBKEYS.get(re.sub(r"\s+", "_", m.group(1).strip().lower()))
        if not key:
            continue
        val = m.group(2).strip()
        out[key] = [v.strip() for v in val.split(",") if v.strip()] if key in _LIST_FIELDS else val
    return out


def idea_verdict(card: IdeaCard, *, gate: dict, recommendation: dict,
                 falsified_critical: int, linked_evidence: int,
                 falsified_notes: list[str] | None = None) -> dict:
    """Deterministic verdict. Order of the guards is the policy."""
    reasons: list[str] = []
    decision = recommendation.get("decision", "")
    if falsified_critical > 0:
        verdict = "STOP_OR_PIVOT"
        reasons.append(f"{falsified_critical} critical hypothesis/assumption(s) contradicted by a "
                       "completed test")
        reasons.extend(f"contradicted: {n}" for n in (falsified_notes or [])[:3])
    elif card.missing_essential():
        verdict = "DEFINE_THE_IDEA"
        reasons.append("missing: " + ", ".join(card.missing_essential()))
    elif gate.get("speculative") or linked_evidence == 0:
        verdict = "NOT_ENOUGH_EVIDENCE"
        reasons.append("no gathered evidence overlaps the stated problem and customer")
    else:
        verdict = _DECISION_TO_VERDICT.get(decision, "RESEARCH_MORE")
        reasons.append(f"specialist recommendation: {decision or 'n/a'}")
        if gate.get("missing"):
            reasons.append("coverage still missing: " + ", ".join(gate["missing"][:4]))
        if verdict in POSITIVE_VERDICTS:
            checks = gate.get("checks", {})
            unmet = [k for k in POSITIVE_VERDICT_REQUIRES if not checks.get(k)]
            if unmet:
                # Falsification first: never recommend spending effort on an idea whose
                # counterevidence or competition was not actually researched.
                verdict = "RESEARCH_MORE"
                reasons.append("a positive verdict requires: " + ", ".join(unmet))
    return {
        "verdict": verdict,
        "meaning": VERDICTS[verdict],
        "positive": verdict in POSITIVE_VERDICTS,
        "reasons": reasons,
        "linked_evidence": linked_evidence,
        "note": ("Desk research can justify a test; only customer behaviour can validate an idea. "
                 "Absence of evidence is not evidence of absence."),
    }


_NOTE_KEYS = ("type", "participants", "success", "fail", "biases", "cost", "decision", "opp", "info_gain")


def parse_test_note(note: str) -> dict:
    """Experiment.decision_note is '; '-joined 'key=value'. Returns the known keys only."""
    out: dict = {}
    for part in (note or "").split("; "):
        key, sep, value = part.partition("=")
        if sep and key.strip() in _NOTE_KEYS:
            out[key.strip()] = value.strip()
    return out
