"""Claim-support verification (INVARIANT-005).

quote ∈ source proves EXISTENCE. This module asks the second, harder
question: does the quoted passage actually SUPPORT the claim text?

Deterministic, fail-closed linguistic checks — no model required, works
offline, and every rejection is explainable via `reasons`. An LLM-based NLI
layer may be added later, but deterministic CONTRADICTS verdicts always win
(fail-closed against meaning inversion).

Verdict ladder (spec §23):
    ENTAILS > STRONGLY_SUPPORTS > PARTIALLY_SUPPORTS > WEAKLY_SUPPORTS
    > NEUTRAL > CONTRADICTS / UNRELATED

Only ENTAILS/STRONGLY_SUPPORTS/PARTIALLY_SUPPORTS may feed grounded
high-confidence synthesis (enforced in reasoning/evidence_quality.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_VERDICT_ORDER = {
    "ENTAILS": 6, "STRONGLY_SUPPORTS": 5, "PARTIALLY_SUPPORTS": 4,
    "WEAKLY_SUPPORTS": 3, "NEUTRAL": 2, "CONTRADICTS": 1, "UNRELATED": 0,
}
_SCORE = {"ENTAILS": 0.95, "STRONGLY_SUPPORTS": 0.8, "PARTIALLY_SUPPORTS": 0.55,
          "WEAKLY_SUPPORTS": 0.3, "NEUTRAL": 0.15, "CONTRADICTS": 0.0,
          "UNRELATED": 0.0}

_STOP = {"the", "and", "for", "with", "that", "this", "from", "have", "has",
         "was", "were", "are", "their", "they", "its", "not", "but", "than",
         "into", "over", "after", "before", "between", "more", "most",
         "less", "least", "also", "been", "being", "which", "will", "would",
         "could", "should", "may", "might", "must", "about", "when", "while"}

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?\s?(?:%|percent|percentage points?)?", re.I)

_NEG_RE = re.compile(
    r"\b(not|no|never|none|cannot|can'?t|won'?t|doesn'?t|does not|don'?t|"
    r"did not|didn'?t|isn'?t|aren'?t|without|fail(?:s|ed)? to|lack(?:s|ed)?|"
    r"unlikely|unable)\b", re.I)

_HEDGE_RE = re.compile(
    r"\b(may|might|could|possibly|perhaps|appears? to|seems? to|suggest\w*|"
    r"preliminary|indicative|some|several|certain)\b", re.I)

_QUANTIFIER_RE = re.compile(r"\b(up to|at least|at most|as many as|no more than|"
                            r"approximately|about|around|roughly|nearly)\b", re.I)

_CONTRAST_RE = re.compile(r"\b(but|although|though|however|unless|except|"
                          r"whereas|while|despite|in contrast|nevertheless|"
                          r"on the other hand|yet)\b", re.I)

_CAUSAL_RE = re.compile(r"\b(causes?|caused|because|due to|leads? to|led to|"
                        r"results? in|drives?|driving|responsible for)\b", re.I)
_CORR_RE = re.compile(r"\b(associat\w+|correlat\w+|linked to|coincid\w+|"
                      r"alongside|tends? to co-?occur)\b", re.I)

_UP_WORDS = re.compile(r"\b(increas\w*|grew|growth|rose|rise|Risen|improv\w*|"
                       r"higher|stronger|expand\w*|gain\w*|boost\w*|up \d)", re.I)
_DOWN_WORDS = re.compile(r"\b(decreas\w*|fell|fall\w*|drop\w*|declin\w*|lower|"
                         r"weaker|reduc\w*|shrink\w*|loss\w*|wors\w*|down \d)", re.I)


@dataclass
class ClaimSupport:
    verdict: str
    score: float
    reasons: list[str] = field(default_factory=list)

    @property
    def supports(self) -> bool:
        return self.verdict in ("ENTAILS", "STRONGLY_SUPPORTS",
                                "PARTIALLY_SUPPORTS")


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]{3,}", (text or "").lower())
            if t not in _STOP}


def _stems(text: str) -> set[str]:
    """Light stemming for relatedness: 5-char prefixes collapse
    inflections (reduced/reduction -> reduc). Deliberately shallow."""
    return {t[:5] for t in _tokens(text)}


def _clauses(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;!?])\s+|,\s+(?=although|but|though|however|"
                     r"whereas|while|despite)|\s+(?:but|however|although|"
                     r"though|whereas|despite|yet)\s+", text or "")
    return [p.strip() for p in parts if p.strip()]


def _numbers(text: str) -> set[str]:
    out = set()
    for m in _NUM_RE.finditer(text or ""):
        tok = re.sub(r"\s+", "", m.group(0).lower())
        tok = tok.replace(",", "").rstrip(".")
        if tok.rstrip("%.").isdigit() or tok.endswith("%"):
            out.add(tok)
    return out


def _direction(word_set_matcher, text: str) -> bool:
    return bool(word_set_matcher.search(text or ""))


def verify_claim_support(claim_text: str, quote: str) -> ClaimSupport:
    """Return the support relationship between a claim and its quotation.
    Fail-closed: ambiguity degrades the verdict, never inflates it."""
    claim = (claim_text or "").strip()
    quote = (quote or "").strip()
    reasons: list[str] = []
    if len(_tokens(claim)) == 0 or len(quote) == 0:
        return ClaimSupport("NEUTRAL", _SCORE["NEUTRAL"], ["empty side"])

    ctoks = _tokens(claim)
    qtoks = _tokens(quote)
    cstems, qstems = _stems(claim), _stems(quote)
    stem_overlap = cstems & qstems
    cov = len(stem_overlap) / max(1, len(cstems))
    # topic tokens for clause-level checks: full words sharing a stem with claim
    topics = sorted({q for q in qtoks if q[:5] in stem_overlap},
                    key=len, reverse=True)[:6]

    # --- A. relatedness -----------------------------------------------------
    if cov < 0.34:
        return ClaimSupport("UNRELATED", _SCORE["UNRELATED"],
                            [f"claim vocabulary coverage {cov:.2f} below floor"])
    if cov < 0.60:
        reasons.append(f"partial vocabulary coverage {cov:.2f}")
        floor = "WEAKLY_SUPPORTS"
    else:
        floor = None

    verdict = "STRONGLY_SUPPORTS"
    qclauses = _clauses(quote)
    cnums = _numbers(claim)
    qnums = _numbers(quote)

    # --- B. numeric integrity ----------------------------------------------
    if cnums:
        missing = {n for n in cnums if n not in qnums}
        if missing:
            if qnums:
                # the quote speaks to the same metric with DIFFERENT figures;
                # strong topical overlap makes this a contradiction, weak
                # overlap only degrades (fail-closed either way)
                reasons.append(f"figure mismatch: claim {sorted(missing)} "
                               f"vs quote {sorted(qnums)}")
                if cov >= 0.6:
                    return ClaimSupport("CONTRADICTS", _SCORE["CONTRADICTS"], reasons)
                floor = floor or "WEAKLY_SUPPORTS"
            else:
                reasons.append(f"claim numbers absent from quote: {sorted(missing)}")
                floor = floor or "PARTIALLY_SUPPORTS"

    # --- C/D. negation flip + contrast-clause inversion ----------------------
    claim_neg = bool(_NEG_RE.search(claim))
    for cl in qclauses:
        cl_low = cl.lower()
        shared = [t for t in topics if t in _tokens(cl)]
        if not shared:
            continue
        cl_neg = bool(_NEG_RE.search(cl))
        if cl_neg != claim_neg and shared:
            # one side negated where the other affirms the same topic
            if claim_neg is False and cl_neg:
                reasons.append(f"negation flip on topic(s) {shared[:3]}: "
                               "quote clause negates what claim asserts")
                return ClaimSupport("CONTRADICTS", _SCORE["CONTRADICTS"], reasons)
            reasons.append(f"claim adds negation absent in quote ({shared[:3]})")
            floor = floor or "PARTIALLY_SUPPORTS"
        # direction inversion on shared topic inside a contrast structure
        if _CONTRAST_RE.search(quote):
            up_c, down_c = _direction(_UP_WORDS, claim), _direction(_DOWN_WORDS, claim)
            up_q, down_q = _direction(_UP_WORDS, cl), _direction(_DOWN_WORDS, cl)
            if (up_c and down_q) or (down_c and up_q):
                reasons.append("contrast-clause direction inversion: quote's "
                               f"contrasting clause moves opposite the claim "
                               f"on {shared[:3]}")
                return ClaimSupport("CONTRADICTS", _SCORE["CONTRADICTS"], reasons)

    # whole-quote direction check (contrast marker anywhere)
    if _CONTRAST_RE.search(quote):
        up_c, down_c = _direction(_UP_WORDS, claim), _direction(_DOWN_WORDS, claim)
        tail = qclauses[-1].lower() if qclauses else ""
        if shared_topics_tail := [t for t in topics if t in _tokens(tail)]:
            if (up_c and _direction(_DOWN_WORDS, tail)) or \
               (down_c and _direction(_UP_WORDS, tail)):
                reasons.append(f"claim ignores contrasting outcome for "
                               f"{shared_topics_tail[:3]} (clause stripping)")
                return ClaimSupport("CONTRADICTS", _SCORE["CONTRADICTS"], reasons)

    # --- E. hedging / quantifier escalation ---------------------------------
    hedge_hits = _HEDGE_RE.findall(quote)
    if hedge_hits and not _HEDGE_RE.search(claim):
        reasons.append(f"claim drops quote hedging ({hedge_hits[:3]})")
        floor = floor or "WEAKLY_SUPPORTS"
    if _QUANTIFIER_RE.search(quote) and not _QUANTIFIER_RE.search(claim):
        reasons.append("claim tightens quote quantifier ('up to'/'about' …)")
        floor = floor or "PARTIALLY_SUPPORTS"

    # --- F. causality escalation --------------------------------------------
    if _CORR_RE.search(quote) and _CAUSAL_RE.search(claim):
        reasons.append("claim upgrades correlation to causation")
        floor = floor or "WEAKLY_SUPPORTS"

    if floor is not None:
        verdict = floor if _VERDICT_ORDER[floor] < _VERDICT_ORDER[verdict] else verdict

    # --- G. entailment bonus -------------------------------------------------
    if verdict == "STRONGLY_SUPPORTS" and cov >= 0.9 and not cnums:
        first_clause = qclauses[0] if qclauses else quote
        if ctoks <= _tokens(first_clause) | qtoks and \
                all(t in _tokens(first_clause) for t in list(ctoks)[:8]):
            verdict = "ENTAILS"
            reasons.append("claim content fully contained in leading passage")

    if not reasons:
        reasons.append(f"vocabulary coverage {cov:.2f}; no violations detected")
    return ClaimSupport(verdict, _SCORE[verdict], reasons)


def status_for_support(status_now, verdict: str):
    """Map a support verdict onto the evidence lifecycle (INVARIANT-005).
    CONTRADICTS/UNRELATED are REJECTED (kept for audit, excluded from
    synthesis); NEUTRAL becomes UNVERIFIED; otherwise unchanged."""
    from research_engine.models.enums import EvidenceStatus
    if verdict in ("CONTRADICTS", "UNRELATED"):
        return EvidenceStatus.REJECTED
    if verdict == "NEUTRAL" and status_now == EvidenceStatus.EXTRACTED:
        return EvidenceStatus.UNVERIFIED
    return status_now


SUPPORT_FACTOR = {
    "ENTAILS": 1.0, "STRONGLY_SUPPORTS": 0.9, "PARTIALLY_SUPPORTS": 0.6,
    "WEAKLY_SUPPORTS": 0.3, "NEUTRAL": 0.1, "CONTRADICTS": 0.0,
    "UNRELATED": 0.0, "": 0.7,   # legacy rows predating the checker
}
