"""Phase 3 reasoning models: hypotheses, assumptions, methodologies, experiments.

Grounding rules baked into the schema:
- every hypothesis records its provenance kind (evidence/contradiction/gap/assumption/user)
- falsification conditions are mandatory; missing ones degrade quality
- versions are immutable history; the live row points at the latest version
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from research_engine.models.base import Entity


class Hypothesis(Entity):
    PREFIX: ClassVar[str] = "hyp"

    title: str = ""
    statement: str = ""
    domain: str = "scientific"          # scientific | startup
    type: str = "CAUSAL"                # see HYPOTHESIS_TYPES
    status: str = "PROPOSED"            # see HYPOTHESIS_STATES
    origin: str = "gap"                 # evidence | contradiction | gap | assumption | user
    origin_refs: list[str] = Field(default_factory=list)   # ids it was derived from

    supporting_evidence: list[str] = Field(default_factory=list)   # ev_ ids
    contradicting_evidence: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)           # asm_ ids
    predictions: list[str] = Field(default_factory=list)
    falsification_conditions: list[str] = Field(default_factory=list)
    discriminating_tests: list[str] = Field(default_factory=list)  # vs alternatives
    alternative_of: str = ""            # parent hypothesis this competes with
    research_questions: list[str] = Field(default_factory=list)

    candidate_methods: list[str] = Field(default_factory=list)

    # multi-dimensional quality (spec #10) — never collapse to one opaque number
    scores: dict = Field(default_factory=dict)   # {support, opposition, testability,
                                                 #  falsifiability, novelty, importance,
                                                 #  parsimony, explanatory_power, feasibility}
    confidence: float = 0.0
    novelty_status: str = "uncertain"   # likely_novel | possibly_novel | incremental |
                                        # already_explored | uncertain
    version: int = 1
    iteration: int = 0


class HypothesisVersion(Entity):
    """Immutable snapshot of a hypothesis revision (spec #14)."""
    PREFIX: ClassVar[str] = "hypv"

    hypothesis_id: str = ""
    version: int = 1
    snapshot: dict = Field(default_factory=dict)
    change_reason: str = ""
    new_evidence_ids: list[str] = Field(default_factory=list)
    confidence_before: float = 0.0
    confidence_after: float = 0.0


class Assumption(Entity):
    PREFIX: ClassVar[str] = "asm2"

    statement: str = ""
    kind: str = "critical"              # critical | important | secondary | minor
    category: str = ""                  # customer_frequency | willingness_to_pay | ...
    status: str = "unverified"          # unverified | testing | validated | invalidated
    importance: float = 0.8
    uncertainty: float = 0.9
    impact_of_failure: float = 0.7      # how much breaks if this fails
    ease_of_testing: float = 0.5        # cheap tests first (spec #18)
    depends_on: list[str] = Field(default_factory=list)   # upstream assumption ids
    hypothesis_id: str = ""             # owning hypothesis (if any)
    opportunity_id: str = ""            # owning opportunity (if any)
    evidence_ids: list[str] = Field(default_factory=list)
    falsification_test: str = ""

    @property
    def priority(self) -> float:
        """Test consequential + cheaply falsifiable things first (spec #18)."""
        return round(self.importance * self.impact_of_failure *
                     self.uncertainty * (0.3 + 0.7 * self.ease_of_testing), 4)


class ResearchQuestion(Entity):
    PREFIX: ClassVar[str] = "rq3"

    question: str = ""
    motivation: str = ""
    gap_ref: str = ""                   # gap that motivated it
    evidence_ids: list[str] = Field(default_factory=list)
    importance: float = 0.5
    novelty: float = 0.5
    testability: float = 0.5
    feasibility: float = 0.5

    @property
    def rank_score(self) -> float:
        """Not novelty-only; infeasible spectacular questions sink (spec #20)."""
        return round(0.25 * self.importance + 0.15 * self.novelty +
                     0.25 * self.testability + 0.35 * self.feasibility, 4)


class Methodology(Entity):
    PREFIX: ClassVar[str] = "meth"

    hypothesis_id: str = ""
    tier: str = "balanced"              # cheap_fast | balanced | high_rigor
    experiment_kind: str = "experiment"  # experiment|ablation|benchmark|observational|
                                         # user_study|survey|interview|ab_test|prototype_test|
                                         # field_test|simulation
    objective: str = ""
    independent_vars: list[str] = Field(default_factory=list)
    dependent_vars: list[str] = Field(default_factory=list)
    control_vars: list[str] = Field(default_factory=list)
    confounders: list[str] = Field(default_factory=list)
    dataset: str = ""
    method_summary: str = ""
    baselines: list[dict] = Field(default_factory=list)   # {name, tier, why_included_or_excluded}
    metrics: list[dict] = Field(default_factory=list)     # {name, why_tied_to_hypothesis}
    ablation_plan: list[str] = Field(default_factory=list)
    procedure: list[str] = Field(default_factory=list)
    success_condition: str = ""
    failure_condition: str = ""
    inconclusive_condition: str = ""
    statistical_notes: str = ""
    reproducibility: dict = Field(default_factory=dict)   # seeds, deps, hardware...
    expected_result: str = ""
    risks: list[str] = Field(default_factory=list)
    comparison: dict = Field(default_factory=dict)        # filled by methodology critic/comparator


class Experiment(Entity):
    PREFIX: ClassVar[str] = "exp"

    hypothesis_id: str = ""
    methodology_id: str = ""
    title: str = ""
    risk_level: str = "LOW_RISK"        # LOW_RISK | MEDIUM_RISK | HIGH_RISK
    status: str = "DESIGNED"
    # lifecycle (spec #76): DESIGNED -> READY_FOR_HUMAN_APPROVAL ->
    # READY_FOR_EXECUTION -> TESTING -> RESULT_INGESTED -> EVALUATED
    requires_human_approval: bool = True
    approved_by_user: bool = False
    decision_note: str = ""

    @property
    def awaiting_approval(self) -> bool:
        return self.status == "READY_FOR_HUMAN_APPROVAL"


class ExperimentResult(Entity):
    PREFIX: ClassVar[str] = "expres"

    experiment_id: str = ""
    hypothesis_id: str = ""
    observations: list[str] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)          # measured values only
    raw_notes: str = ""                                  # never overwritten by interpretation
    interpretation: str = ""
    verdict: str = ""                    # supports | contradicts | inconclusive
    confidence: float = 0.0
    limitations: list[str] = Field(default_factory=list)
    source_kind: str = "user_provided"   # provenance: experiment results differ from web sources
