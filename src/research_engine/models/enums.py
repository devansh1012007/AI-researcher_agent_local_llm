"""All system enumerations. Single source of truth for statuses and categories."""
from __future__ import annotations

from enum import Enum


class ProjectState(str, Enum):
    CREATED = "CREATED"
    CLARIFYING = "CLARIFYING"
    PLANNED = "PLANNED"
    SEARCHING = "SEARCHING"
    FETCHING = "FETCHING"
    EXTRACTING = "EXTRACTING"
    VERIFYING = "VERIFYING"
    ANALYZING_GAPS = "ANALYZING_GAPS"
    GENERATING_FOLLOWUPS = "GENERATING_FOLLOWUPS"
    ITERATING = "ITERATING"
    CONVERGED = "CONVERGED"
    SYNTHESIZING = "SYNTHESIZING"
    COMPLETED = "COMPLETED"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskType(str, Enum):
    CLARIFY_PROBLEM = "CLARIFY_PROBLEM"
    GENERATE_RESEARCH_PLAN = "GENERATE_RESEARCH_PLAN"
    GENERATE_QUERY = "GENERATE_QUERY"
    SEARCH = "SEARCH"
    FETCH = "FETCH"
    CLEAN_DOCUMENT = "CLEAN_DOCUMENT"
    CHUNK_DOCUMENT = "CHUNK_DOCUMENT"
    EXTRACT_EVIDENCE = "EXTRACT_EVIDENCE"
    VALIDATE_EVIDENCE = "VALIDATE_EVIDENCE"
    DEDUPLICATE = "DEDUPLICATE"
    DETECT_CONTRADICTIONS = "DETECT_CONTRADICTIONS"
    DETECT_GAPS = "DETECT_GAPS"
    GENERATE_FOLLOWUP_QUERIES = "GENERATE_FOLLOWUP_QUERIES"
    EVALUATE_CONVERGENCE = "EVALUATE_CONVERGENCE"
    SYNTHESIZE_REPORT = "SYNTHESIZE_REPORT"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    DEAD = "DEAD"  # exhausted retries; terminal


class SourceType(str, Enum):
    RESEARCH_PAPER = "research_paper"
    ACADEMIC_DATASET = "academic_dataset"
    GOVERNMENT = "government"
    COMPANY = "company"
    FINANCIAL_FILING = "financial_filing"
    INDUSTRY_REPORT = "industry_report"
    NEWS = "news"
    FORUM = "forum"
    BLOG = "blog"
    DOCUMENTATION = "documentation"
    SEARCH_RESULT = "search_result"
    OTHER = "other"
    # --- Phase 3: first-hand provenance, distinguished from web sources (#59) ---
    EXPERIMENT_RESULT = "experiment_result"
    USER_OBSERVATION = "user_observation"
    USER_INTERVIEW = "user_interview"
    SURVEY_RESULT = "survey_result"
    PROTOTYPE_RESULT = "prototype_result"
    SIMULATION_RESULT = "simulation_result"
    INTERNAL_DATA = "internal_data"


# Tier 1 primary ... Tier 5 unknown/low. Prior about quality, NOT proof of correctness.
TIER_BY_SOURCE_TYPE: dict[SourceType, int] = {
    SourceType.RESEARCH_PAPER: 1,
    SourceType.ACADEMIC_DATASET: 1,
    SourceType.GOVERNMENT: 1,
    SourceType.FINANCIAL_FILING: 1,
    SourceType.DOCUMENTATION: 2,
    SourceType.COMPANY: 2,
    SourceType.INDUSTRY_REPORT: 2,
    SourceType.NEWS: 3,
    SourceType.BLOG: 4,
    SourceType.FORUM: 4,
    SourceType.SEARCH_RESULT: 5,
    SourceType.OTHER: 5,
}


class ContentStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    FETCHED = "FETCHED"
    PARSED = "PARSED"
    FAILED = "FAILED"
    DUPLICATE = "DUPLICATE"
    BLOCKED = "BLOCKED"


class ClaimKind(str, Enum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    ASSUMPTION = "ASSUMPTION"


class EvidenceStatus(str, Enum):
    EXTRACTED = "EXTRACTED"
    SUPPORTED = "SUPPORTED"
    WEAKLY_SUPPORTED = "WEAKLY_SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNVERIFIED = "UNVERIFIED"
    REJECTED = "REJECTED"


class GapCategory(str, Enum):
    MISSING_INFORMATION = "MISSING_INFORMATION"
    WEAK_EVIDENCE = "WEAK_EVIDENCE"
    MISSING_SOURCE_TYPE = "MISSING_SOURCE_TYPE"
    CONTRADICTION = "CONTRADICTION"
    OUTDATED_INFORMATION = "OUTDATED_INFORMATION"
    UNVERIFIED_NUMERIC_CLAIM = "UNVERIFIED_NUMERIC_CLAIM"
    MISSING_ALTERNATIVE_EXPLANATION = "MISSING_ALTERNATIVE_EXPLANATION"
    UNDERREPRESENTED_SUBTOPIC = "UNDERREPRESENTED_SUBTOPIC"
    # --- Phase 2 structural gaps ---
    INFORMATION_GAP = "INFORMATION_GAP"
    EVIDENCE_GAP = "EVIDENCE_GAP"
    SOURCE_DIVERSITY_GAP = "SOURCE_DIVERSITY_GAP"
    METHOD_COMPARISON_GAP = "METHOD_COMPARISON_GAP"
    TIME_GAP = "TIME_GAP"
    GEOGRAPHIC_GAP = "GEOGRAPHIC_GAP"
    CUSTOMER_SEGMENT_GAP = "CUSTOMER_SEGMENT_GAP"
    COMPETITOR_GAP = "COMPETITOR_GAP"
    BENCHMARK_GAP = "BENCHMARK_GAP"
    BASELINE_GAP = "BASELINE_GAP"
    VALIDATION_GAP = "VALIDATION_GAP"
    CAUSALITY_GAP = "CAUSALITY_GAP"
    INDEPENDENT_REPLICATION_GAP = "INDEPENDENT_REPLICATION_GAP"
    NEGATIVE_EVIDENCE_GAP = "NEGATIVE_EVIDENCE_GAP"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# --- Phase 3: reasoning lifecycle enums ---

class HypothesisState(str, Enum):
    PROPOSED = "PROPOSED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_EVIDENCE = "NEEDS_EVIDENCE"
    REFINED = "REFINED"
    READY_FOR_TEST = "READY_FOR_TEST"
    TESTING = "TESTING"
    SUPPORTED = "SUPPORTED"
    WEAKLY_SUPPORTED = "WEAKLY_SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    FALSIFIED = "FALSIFIED"
    ABANDONED = "ABANDONED"
    SUPERSEDED = "SUPERSEDED"


HYPOTHESIS_STATES = [s.value for s in HypothesisState]

HYPOTHESIS_TYPES = [
    "DESCRIPTIVE", "CORRELATIONAL", "CAUSAL", "MECHANISTIC", "PREDICTIVE",
    "COMPARATIVE", "ENGINEERING", "MARKET", "CUSTOMER", "BUSINESS_MODEL",
    "DISTRIBUTION", "WILLINGNESS_TO_PAY",
]

# qualitative evidence stances (spec #62) — no fake Bayes
EVIDENCE_STANCES = [
    "strongly_supports", "moderately_supports", "weakly_supports",
    "neutral", "weakly_contradicts", "strongly_contradicts",
]

# startup validation evidence hierarchy (spec #66): behavioral > stated (spec #102)
VALIDATION_EVIDENCE_HIERARCHY = {
    "casual_opinion": 0.1,
    "survey_intention": 0.3,
    "interview_evidence": 0.5,
    "prototype_usage": 0.7,
    "repeated_behavioral_usage": 0.9,
    "payment": 1.0,
}


class StopReason(str, Enum):
    CONVERGED = "CONVERGED"
    PROVIDER_DEGRADED = "PROVIDER_DEGRADED"   # failure, NOT saturation (P0-04)
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    MAX_ITERATIONS = "MAX_ITERATIONS"
    NO_HIGH_VALUE_GAPS = "NO_HIGH_VALUE_GAPS"
    USER_STOPPED = "USER_STOPPED"
    FAILED = "FAILED"


class ReviewGate(str, Enum):
    AFTER_PROBLEM_DEFINITION = "AFTER_PROBLEM_DEFINITION"
    AFTER_INITIAL_RESEARCH_PLAN = "AFTER_INITIAL_RESEARCH_PLAN"
    AFTER_FIRST_RESEARCH_CYCLE = "AFTER_FIRST_RESEARCH_CYCLE"
    BEFORE_FINAL_SYNTHESIS = "BEFORE_FINAL_SYNTHESIS"


class BranchCategory(str, Enum):
    # academic
    FOUNDATIONS = "FOUNDATIONS"
    CURRENT_STATE = "CURRENT_STATE"
    METHODS = "METHODS"
    COMPETING_APPROACHES = "COMPETING_APPROACHES"
    EVIDENCE = "EVIDENCE"
    BENCHMARKS = "BENCHMARKS"
    LIMITATIONS = "LIMITATIONS"
    CONTRADICTIONS = "CONTRADICTIONS"
    APPLICATIONS = "APPLICATIONS"
    OPEN_PROBLEMS = "OPEN_PROBLEMS"
    # startup
    MARKET = "MARKET"
    CUSTOMERS = "CUSTOMERS"
    PAIN = "PAIN"
    ALTERNATIVES = "ALTERNATIVES"
    COMPETITORS = "COMPETITORS"
    PRICING = "PRICING"
    DISTRIBUTION = "DISTRIBUTION"
    REGULATIONS = "REGULATIONS"
    TECHNOLOGY = "TECHNOLOGY"
    FUNDING = "FUNDING"
    TIMING = "TIMING"
    RISKS = "RISKS"
    GENERIC = "GENERIC"


ACADEMIC_CATEGORIES = [
    BranchCategory.FOUNDATIONS, BranchCategory.CURRENT_STATE, BranchCategory.METHODS,
    BranchCategory.COMPETING_APPROACHES, BranchCategory.EVIDENCE, BranchCategory.BENCHMARKS,
    BranchCategory.LIMITATIONS, BranchCategory.CONTRADICTIONS, BranchCategory.APPLICATIONS,
    BranchCategory.OPEN_PROBLEMS,
]
STARTUP_CATEGORIES = [
    BranchCategory.MARKET, BranchCategory.CUSTOMERS, BranchCategory.PAIN,
    BranchCategory.ALTERNATIVES, BranchCategory.COMPETITORS, BranchCategory.PRICING,
    BranchCategory.DISTRIBUTION, BranchCategory.REGULATIONS, BranchCategory.TECHNOLOGY,
    BranchCategory.FUNDING, BranchCategory.TIMING, BranchCategory.RISKS,
]
