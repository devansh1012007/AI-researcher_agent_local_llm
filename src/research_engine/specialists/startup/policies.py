"""Startup domain policies: taxonomies, source routing, freshness, hierarchies.

Pure data + small pure functions. No IO. These encode the spec's domain
knowledge so analyzers stay mechanical and testable.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- pain taxonomy
# 14 pain categories (spec #13) with detection hints.
PAIN_CATEGORIES: dict[str, re.Pattern] = {
    "time": re.compile(r"\b(hours?|days?|weeks?|time[- ]consuming|slow|takes too long|waste\w* time)\b", re.I),
    "cost": re.compile(r"\b(expensive|costly|fees?|pricey|too much money|budget)\b", re.I),
    "revenue_loss": re.compile(r"\b(lost (?:sales|revenue|customers?)|churn|missed (?:orders?|leads?))\b", re.I),
    "risk": re.compile(r"\b(risk\b|risky|liability|exposure|breach|fraud)\b", re.I),
    "compliance": re.compile(r"\b(complian\w+|regulat\w+|audit|gdpr|mandat\w+)\b", re.I),
    "complexity": re.compile(r"\b(complex|complicated|confus\w+|overwhelm\w+|too many)\b", re.I),
    "manual_labor": re.compile(r"\b(manual\w*|by hand|copy[- ]past\w+|spreadsheet|excel)\b", re.I),
    "poor_ux": re.compile(r"\b(confusing ui|bad ux|clunky|unintuitive|hard to use)\b", re.I),
    "slow_workflow": re.compile(r"\b(latency|lag\w*|queue|wait\w*|backlog)\b", re.I),
    "integration_failure": re.compile(r"\b(integrat\w+|api (?:breaks?|limits?)|sync (?:fails?|issues?)|connector)\b", re.I),
    "lack_of_capability": re.compile(r"\b(no (?:support|feature|option|way) to|can'?t \w+|missing feature|doesn'?t support)\b", re.I),
    "quality_problems": re.compile(r"\b(bugs?|errors?|breaks|crash\w*|inaccura\w+|wrong)\b", re.I),
    "coordination_problems": re.compile(r"\b(coordinat\w+|handoff|between teams|alignment|communication gap)\b", re.I),
    "information_problems": re.compile(r"\b(no visibility|blind spot|don'?t know|lack of (?:data|insight)|scattered)\b", re.I),
}

# Pain evidence hierarchy (spec #14): stronger behavioral forms weigh more.
# Overlaps VALIDATION_EVIDENCE_HIERARCHY but is pain-specific.
PAIN_EVIDENCE_HIERARCHY: dict[str, float] = {
    "reported_pain": 0.2,
    "observed_workaround": 0.45,
    "repeated_behavior": 0.6,
    "existing_spending": 0.8,
    "switching_behavior": 0.85,
    "actual_payment": 1.0,
}


def classify_pain(text: str) -> list[str]:
    cats = [c for c, rx in PAIN_CATEGORIES.items() if rx.search(text)]
    return cats or ["unclassified"]


def pain_evidence_class(claim_text: str) -> str:
    """Classify the STRONGEST evidence form present in a pain claim."""
    t = claim_text.lower()
    # Vendor pricing describes the SELLER's number, not customer spending;
    # it must never count as behavioral demand evidence (spec #14/#43).
    if re.search(r"\b(price[sd]?|pricing|charges?|lists? at)\b", t) and \
            not re.search(r"\b(paid|paying|pays|spends?|budget)\b", t):
        return "reported_pain"
    if re.search(r"\b(paid|paying|pays?|payment|invoice|spent \$?₹?€?£?\d|spends? \$?₹?€?£?\d)", t):
        return "actual_payment"
    if re.search(r"\b(switch\w+ from|migrat\w+ from|cancel\w+|churn\w* from|left \w+ for)\b", t):
        return "switching_behavior"
    if re.search(r"\b(spend\w* (?:hours|money)|budget of|\$\d|₹\d|per month)\b", t):
        return "existing_spending"
    if re.search(r"\b(every day|daily|weekly|each week|every week|often|repeatedly|always|keeps?)\b", t):
        return "repeated_behavior"
    if re.search(r"\b(workaround|manually|copy[- ]paste|export to|in excel|in a spreadsheet)\b", t):
        return "observed_workaround"
    return "reported_pain"


# ---------------------------------------------------------------- competitor taxonomy
COMPETITOR_CLASSES = [
    "direct", "indirect", "substitute", "potential_entrant",
    "platform", "infrastructure_provider", "internal_alternative",
]

PRICING_MODELS = [
    "subscription", "usage_based", "seat_based", "transaction_fee",
    "freemium", "one_time", "enterprise_contract", "commission",
    "advertising", "service_plus_software",
]

DISTRIBUTION_CHANNELS = [
    "seo", "content", "sales", "partnership", "marketplace", "community",
    "social", "paid_acquisition", "enterprise_procurement", "integrations",
    "referrals", "founder_led_sales",
]

ALTERNATIVE_KINDS = [
    "software", "spreadsheet", "manual_labor", "consultant", "outsourcing",
    "internal_employee", "existing_vendor", "diy", "do_nothing",
]

_OPP_TYPE_HINTS = {
    "workflow_automation": r"\b(automat\w+|manual workflow|repetitive task)\b",
    "vertical_saas": r"\b(industry-specific|vertical|for (?:lawyers|doctors|clinics|contractors|restaurants|schools))\b",
    "infrastructure": r"\b(infrastructure|platform layer|developer platform|sdk|api-first)\b",
    "marketplace": r"\b(marketplace|two-sided|match\w+ buyers|aggregat\w+ supply)\b",
    "developer_tooling": r"\b(developer\w*|devops|ci/cd|sdk|cli tool)\b",
    "consumer_product": r"\b(consumers?|b2c|individual users|households)\b",
    "b2b_service": r"\b(managed service|agency|service layer|done-for-you)\b",
    "b2b_software": r"\b(b2b|saas|enterprise software|business software)\b",
    "fintech": r"\b(payment\w*|lending|credit|insurance tech|neobank|ledger)\b",
    "healthtech": r"\b(clinic\w*|patients?|ehr|telemedicine|diagnost\w+)\b",
    "industrial": r"\b(factory|manufactur\w+|logistics|warehouse|supply chain)\b",
    "education": r"\b(students?|schools?|edtech|learning|tutor\w+)\b",
    "logistics": r"\b(fleet|last[- ]mile|delivery|freight|shipment\w*)\b",
}


def opportunity_type(text: str) -> str:
    """Extensible taxonomy classification (spec #33). Falls back to b2b_software."""
    import re as _re
    for name, hint in _OPP_TYPE_HINTS.items():
        if _re.search(hint, text or "", _re.I):
            return name
    return "b2b_software"


# ---------------------------------------------------------------- source routing
# Question kind -> preferred source categories/tiers (spec #61).
SOURCE_ROUTING: dict[str, dict] = {
    "market_size": {"categories": ["government", "industry_report", "research"],
                    "min_tier": 3,
                    "note": "market size requires definable methodology sources"},
    "pricing": {"categories": ["company", "vendor", "documentation"],
                "min_tier": 3,
                "note": "pricing must come from official pages"},
    "customer_pain": {"categories": ["forum", "community", "review_site", "news"],
                      "min_tier": 5,
                      "note": "pain needs customer-level voices"},
    "funding": {"categories": ["news", "company", "investor"],
                "min_tier": 4,
                "note": "funding needs reputable reporting"},
    "regulation": {"categories": ["government", "regulator", "law_firm"],
                   "min_tier": 3,
                   "note": "regulation needs primary sources"},
    "technical_feasibility": {"categories": ["paper", "documentation", "arxiv"],
                              "min_tier": 4,
                              "note": "feasibility needs papers/docs/experiments"},
}


def route_question_kind(query: str) -> str:
    q = query.lower()
    if re.search(r"market size|tam|sam|som|how big is the market", q):
        return "market_size"
    if re.search(r"pric\w+|costs? \$|charges?|fee\b", q):
        return "pricing"
    if re.search(r"pain|complain|frustrat\w+|struggl\w+|customers? say", q):
        return "customer_pain"
    if re.search(r"funding|raised|series [abc]|invest\w+", q):
        return "funding"
    if re.search(r"regulat\w+|compliance|gdpr|act\b|mandate", q):
        return "regulation"
    if re.search(r"feasib\w+|possible to build|technical|accuracy of", q):
        return "technical_feasibility"
    return "customer_pain"


# ---------------------------------------------------------------- freshness
# Entity-kind freshness policy (spec #63): refresh classes in days.
FRESHNESS_POLICIES: dict[str, int] = {
    "pricing": 30,            # pricing changes fast — refresh frequently
    "competitor": 90,         # periodic refresh
    "market_size": 365,       # follows publication cycles
    "regulation": 14,         # aggressive refresh
    "customer_pain": 180,
    "funding_signal": 7,
    "foundational_research": 730,
}


def freshness_state(kind: str, observed_at: str, today: str) -> str:
    """fresh | aging | stale | unknown — based on policy for `kind`."""
    from datetime import date
    try:
        obs = date.fromisoformat(str(observed_at)[:10])
        now = date.fromisoformat(str(today)[:10])
    except (ValueError, TypeError):
        return "unknown"
    age_days = (now - obs).days
    limit = FRESHNESS_POLICIES.get(kind, 180)
    if age_days <= limit:
        return "fresh"
    if age_days <= limit * 3:
        return "aging"
    return "stale"


# ---------------------------------------------------------------- quality rubric
# Opportunity quality rubric dimensions (spec #34). Weights sum to 1.0;
# every dimension keeps a human-readable reason alongside its score.
RUBRIC_DIMENSIONS: dict[str, float] = {
    "pain_severity": 0.12,
    "pain_frequency": 0.08,
    "economic_value": 0.10,
    "wtp_evidence": 0.12,
    "market_size": 0.06,
    "competition_weakness": 0.10,   # HIGH score == weak competition == good
    "distribution": 0.10,
    "technical_feasibility": 0.06,
    "timing": 0.08,
    "retention_potential": 0.04,
    "defensibility_potential": 0.04,
    "evidence_strength": 0.10,
}


def qualitative(score: float) -> str:
    """No fake precision (spec #35): map 0..1 to qualitative labels."""
    if score >= 0.66:
        return "Strong"
    if score >= 0.4:
        return "Moderate"
    if score > 0:
        return "Weak"
    return "Unknown"


# ---------------------------------------------------------------- readiness
READINESS_LEVELS = ["NOT_READY", "RESEARCH_READY", "VALIDATION_READY",
                    "PILOT_READY", "DECISION_READY"]

# Coverage dimensions required before high-priority presentation (spec #98).
QUALITY_GATE_REQUIREMENTS = [
    "market_defined", "customer_identified", "pain_evidence",
    "alternative_identified", "competition_researched", "pricing_researched",
    "whynow_investigated", "counterevidence_searched",
    "critical_assumptions_identified", "validation_path_exists",
]

# Uncertainty kinds that internet research cannot resolve (spec #70):
# when these dominate, the system must recommend real-world validation.
CUSTOMER_BEHAVIOR_UNCERTAINTIES = {
    "willingness_to_pay", "frequency", "severity", "switching", "retention"}


# ---------------------------------------------------------------- canonical parsing
# INVARIANT: exactly ONE magnitude-aware money parser exists (audit P0-06/P0-07).
_MONEY_RE = re.compile(r"(?P<cur>[$\u20b9\u20ac\u00a3])?\s?(?P<amt>\d[\d,]*(?:\.\d+)?)"
                       r"\s?(?P<mag>trillion|billion|bn|million|mn|mm|k|cr|lakh|b|m)?(?![a-z])",
                       re.I)
_MAGNITUDE = {"trillion": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9,
              "million": 1e6, "mn": 1e6, "mm": 1e6, "m": 1e6,
              "k": 1e3, "cr": 1e7, "lakh": 1e5}
_CURRENCY_BY_SYMBOL = {"$": "USD", "\u20b9": "INR", "\u20ac": "EUR", "\u00a3": "GBP"}

_STATEMENT_KINDS = ("market_size", "revenue", "funding", "valuation",
                    "growth_rate", "percentage", "year", "employee_count",
                    "price", "unknown")

_KIND_ANCHORS = [
    ("growth_rate", re.compile(r"\b(cagr|grew?|growth(?: rate)?|yoy|year[- ]over[- ]year)\b", re.I)),
    ("funding", re.compile(r"\b(rais\w+|funding(?: round)?|series [abc]|seed round|venture)\b", re.I)),
    ("valuation", re.compile(r"\b(valuation|valu\w+ at|valued)\b", re.I)),
    ("revenue", re.compile(r"\b(revenues?|annual sales|arr|mrr)\b", re.I)),
    ("market_size", re.compile(r"\b(market(?: size)?|tam\b|sam\b|som\b|addressable)\b", re.I)),
    ("price", re.compile(r"\b(price[sd]?|pricing|charges?|costs? \$|per month|per seat|per year|/mo|/yr|licen[cs]e|subscription)\b", re.I)),
    ("employee_count", re.compile(r"\b(employees?|staff of|headcount)\b", re.I)),
]


def classify_numeric_statement(text: str) -> str:
    """Classify what a numeric statement is about BEFORE parsing any value."""
    t = text or ""
    # a bare 4-digit year (no currency symbol, no magnitude word) is a YEAR
    has_money_marker = re.search(r"[$\u20b9\u20ac\u00a3]|(?<!\w)(?:trillion|billion|bn|million|mn|mm|cr|lakh)(?!\w)", t, re.I)
    if re.search(r"\b(19|20)\d{2}\b", t) and not has_money_marker:
        return "year"
    for kind, rx in _KIND_ANCHORS:
        if rx.search(t):
            return kind
    if "%" in t or re.search(r"\bpercent\b", t, re.I):
        return "percentage"
    return "unknown"


def parse_money(text: str):
    """Return (value_float, currency, magnitude_word) for the FIRST money
    token whose context classifies as market_size/price/revenue/funding.
    Years, percentages and growth rates are NEVER parsed as values.
    Returns (0.0, "", "") when nothing qualifies."""
    kind = classify_numeric_statement(text)
    if kind not in ("market_size", "price", "revenue", "valuation", "funding",
                    "employee_count"):
        return 0.0, "", ""
    m = _MONEY_RE.search(text or "")
    if not m:
        return 0.0, "", ""
    # bare digits without currency AND without magnitude are not money
    if not m.group("cur") and not m.group("mag"):
        return 0.0, "", ""
    try:
        val = float(m.group("amt").replace(",", ""))
    except ValueError:
        return 0.0, "", ""
    mag = (m.group("mag") or "").lower()
    val *= _MAGNITUDE.get(mag, 1.0)
    cur = _CURRENCY_BY_SYMBOL.get(m.group("cur") or "", "")
    # funding amounts are real values but are NOT market sizes; callers must
    # consult classify_numeric_statement() before using them as such.
    return val, cur, mag
