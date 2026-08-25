"""Startup domain entities (Phase 5).

These extend — never replace — the existing startup models in
models/startup.py and models/opportunity.py. Everything here persists
through the standard per-project Database via StartupRepos (_EXTRA_TABLES),
or through the cross-project market knowledge base (project_id = market slug).
"""
from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field

from research_engine.models.base import Entity


class Market(Entity):
    """A defined market. Definition precedes sizing (spec #7)."""
    PREFIX: ClassVar[str] = "mkt"
    name: str = ""
    definition: str = ""              # what is being sold, to whom, for what use
    geography: str = ""
    time_period: str = ""
    boundaries: list[str] = Field(default_factory=list)      # what counts as IN
    exclusions: list[str] = Field(default_factory=list)      # what is explicitly OUT
    related_markets: list[str] = Field(default_factory=list)
    segments: list[str] = Field(default_factory=list)        # seg_ ids
    drivers: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    regulatory_environment: str = ""
    technology_drivers: list[str] = Field(default_factory=list)
    competitive_structure: str = ""   # e.g. fragmented / concentrated / monopoly-ish
    market_slug: str = ""             # cross-project KB key ("indian-logistics-software")
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0           # computed from evidence coverage, not asserted
    # definition completeness (spec #7): missing dimensions become research gaps
    definition_gaps: list[str] = Field(default_factory=list)


class MarketSizeEstimate(Entity):
    """One market-size figure, fully attributed (spec #8). Never averaged blindly."""
    PREFIX: ClassVar[str] = "msz"
    market_id: str = ""
    value_raw: str = ""               # exactly as written in the source
    value: float = 0.0                # parsed numeric, 0 when unparseable
    currency: str = ""
    year: str = ""                    # the year the estimate refers to
    geography: str = ""
    method: str = ""                  # reported | bottom_up | top_down | TAM | SAM | SOM | unknown
    definition_note: str = ""         # what the source says is included
    source_id: str = ""
    evidence_id: str = ""
    confidence: float = 0.3
    conflict_flag: str = ""           # MARKET_SIZE_CONFLICT when cross-validation fails


class Persona(Entity):
    """Evidence-derived buyer/user persona. Speculative personas are labeled."""
    PREFIX: ClassVar[str] = "pers"
    role: str = ""
    organization_type: str = ""
    company_size: str = ""
    industry: str = ""
    job_to_be_done: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    workflow: str = ""
    pain_points: list[str] = Field(default_factory=list)     # pain_ ids
    existing_tools: list[str] = Field(default_factory=list)
    decision_authority: str = ""      # user != buyer (spec #10)
    purchase_behavior: str = ""
    budget_signal: str = ""
    segment_id: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    speculative: bool = True          # True until >=2 independent evidences support it
    confidence: float = 0.0


class JobToBeDone(Entity):
    PREFIX: ClassVar[str] = "jtbd"
    segment_id: str = ""
    functional_job: str = ""
    emotional_social: str = ""
    trigger: str = ""
    workflow_steps: list[str] = Field(default_factory=list)
    desired_outcome: str = ""
    current_alternative: str = ""
    pain_ids: list[str] = Field(default_factory=list)
    friction: str = ""
    cost_of_failure: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class CurrentAlternative(Entity):
    """What customers do today instead of the proposed solution.
    'Doing nothing' is a legitimate competitor (spec #16)."""
    PREFIX: ClassVar[str] = "alt"
    name: str = ""
    kind: str = ""   # software|spreadsheet|manual|consultant|outsourced|internal|vendor|diy|do_nothing
    used_by_segments: list[str] = Field(default_factory=list)
    inadequacy: str = ""              # why insufficient (evidence-linked when possible)
    switching_cost: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class CompetitorProfile(Entity):
    """Structured competitor intelligence. Existence != traction (kept separate)."""
    PREFIX: ClassVar[str] = "cpx"
    name: str = ""
    product: str = ""
    classification: str = ""  # direct|indirect|substitute|potential_entrant|platform|
                              # infrastructure_provider|internal_alternative
    customer_segment: str = ""
    geography: str = ""
    business_model: str = ""          # pricing model classification (spec #23)
    pricing_summary: str = ""         # normalized summary; raw plans live in PricingPlan
    features: list[str] = Field(default_factory=list)
    integrations: list[str] = Field(default_factory=list)
    distribution_channels: list[str] = Field(default_factory=list)
    channel_evidence: dict = Field(default_factory=dict)  # channel -> observed|inferred|hypothesized
    positioning: str = ""
    funding_signal: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)      # incl. review complaints w/ evidence
    recent_changes: list[str] = Field(default_factory=list)
    traction_note: str = ""           # ONLY what evidence supports; empty otherwise
    evidence_ids: list[str] = Field(default_factory=list)


class PricingPlan(Entity):
    """Normalized pricing observation. Raw string always preserved (spec #22)."""
    PREFIX: ClassVar[str] = "plan"
    competitor_name: str = ""
    tier_name: str = ""
    price_raw: str = ""               # exactly as written
    amount: float = 0.0
    currency: str = ""
    billing_period: str = ""          # monthly|annual|quarterly|one_time|usage|custom
    annualized_normalized: float = 0.0   # best-effort monthly-equivalent; 0 = unknown
    normalization_note: str = ""      # e.g. "annual price /12", "never compared to monthly without note"
    included_limits: str = ""
    target_segment: str = ""
    pricing_model: str = ""           # subscription|usage_based|seat_based|transaction_fee|
                                      # freemium|one_time|enterprise_contract|commission|
                                      # advertising|service_plus_software
    observed_at: str = ""
    source_id: str = ""
    evidence_id: str = ""


class DistributionChannel(Entity):
    PREFIX: ClassVar[str] = "dch"
    name: str = ""   # SEO|content|sales|partnership|marketplace|community|social|paid|
                     # enterprise_procurement|integrations|referrals|founder_led_sales
    used_by: list[str] = Field(default_factory=list)         # competitor names
    evidence_class: str = "hypothesized"  # observed|inferred|hypothesized (spec #24)
    difficulty_notes: str = ""        # CAC signals, sales cycle, procurement barriers (spec #25)
    evidence_ids: list[str] = Field(default_factory=list)


class TechnologyShift(Entity):
    """An enabling change that makes something newly possible (spec #26)."""
    PREFIX: ClassVar[str] = "tsh"
    kind: str = ""  # model_capability|api_availability|cost_reduction|open_source|protocol|
                    # platform|automation|regulatory_change|behavior_change
    description: str = ""
    enables: str = ""                 # what became practical recently
    date_observed: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class OpportunityVersion(Entity):
    """Immutable snapshot of an opportunity at a point in time (spec #96)."""
    PREFIX: ClassVar[str] = "oppv"
    opportunity_id: str = ""
    version: int = 1
    snapshot: dict = Field(default_factory=dict)
    change_reason: str = ""
    new_evidence_ids: list[str] = Field(default_factory=list)
    confidence_before: float = 0.0
    confidence_after: float = 0.0


class OpportunityDecision(Entity):
    """Decision log entry: why we pursue/stop/modify an opportunity (spec #97)."""
    PREFIX: ClassVar[str] = "opd"
    opportunity_id: str = ""
    decision: str = ""   # continue_researching|start_validating|modify|compare|abandon|validate_worthy
    reason: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    assumptions_snapshot: list[str] = Field(default_factory=list)
    readiness: str = ""               # decision-readiness level at time of decision


class FounderProfile(Entity):
    """Founder constraints (spec #50/#84). Input object; kept per-project when given."""
    PREFIX: ClassVar[str] = "fdr"
    skills: list[str] = Field(default_factory=list)
    capital: str = ""
    time_available: str = ""
    geography: str = ""
    network: list[str] = Field(default_factory=list)
    technical_capabilities: list[str] = Field(default_factory=list)
    industry_access: list[str] = Field(default_factory=list)
    risk_preference: str = ""         # conservative|moderate|aggressive
