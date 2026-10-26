"""Registries of valid steps, structural checks, specialists, reports, metrics, and prompt kwargs."""
from __future__ import annotations

from research_engine.models.enums import ProjectState

STEP_REGISTRY: frozenset[str] = frozenset({
    "clarify",
    "ask_user",
    "plan",
    "generate_queries",
    "search",
    "fetch_and_parse",
    "extract_evidence",
    "verify_and_dedup",
    "detect_contradictions",
    "detect_gaps",
    "generate_followups",
    "specialist_pipeline",
    "evaluate_convergence",
    "write_reports",
})

SETUP_STEPS: frozenset[str] = frozenset({
    "clarify",
    "ask_user",
    "plan",
    "generate_queries",
})

ITERATION_STEPS: frozenset[str] = frozenset({
    "search",
    "fetch_and_parse",
    "extract_evidence",
    "verify_and_dedup",
    "detect_contradictions",
    "detect_gaps",
    "generate_followups",
    "specialist_pipeline",
    "evaluate_convergence",
    "ask_user",
})

SYNTHESIS_STEPS: frozenset[str] = frozenset({
    "specialist_pipeline",
    "write_reports",
})

# State machine state associated with each step for static ALLOWED-table simulation
STEP_TARGET_STATE: dict[str, ProjectState] = {
    "clarify": ProjectState.CLARIFYING,
    "ask_user": ProjectState.CLARIFYING,
    "plan": ProjectState.CLARIFYING,
    "generate_queries": ProjectState.PLANNED,
    "search": ProjectState.SEARCHING,
    "fetch_and_parse": ProjectState.FETCHING,
    "extract_evidence": ProjectState.EXTRACTING,
    "verify_and_dedup": ProjectState.VERIFYING,
    "detect_contradictions": ProjectState.ANALYZING_GAPS,
    "detect_gaps": ProjectState.ANALYZING_GAPS,
    "specialist_pipeline": ProjectState.ANALYZING_GAPS,
    "evaluate_convergence": ProjectState.ANALYZING_GAPS,
    "generate_followups": ProjectState.GENERATING_FOLLOWUPS,
    "write_reports": ProjectState.SYNTHESIZING,
}

STRUCTURAL_CHECK_REGISTRY: frozenset[str] = frozenset({
    "source_diversity",
    "negative_evidence",
    "independent_replication",
    "causality",
    "benchmarks",
    "baselines",
    "method_comparison",
    "customer_segments",
    "competitors",
    "validation_evidence",
    "geography",
})

SPECIALIST_REGISTRY: frozenset[str] = frozenset({
    "startup",
})

CORE_REPORT_FILES: frozenset[str] = frozenset({
    "problem.md",
    "research_plan.md",
    "info.md",
    "sources.md",
    "gaps.md",
    "research_log.md",
    "source_trail.md",
})

DOMAIN_REPORT_REGISTRY: dict[str, str] = {
    "literature_review": "literature_review.md",
    "startup_research": "startup_research.md",
}

INTELLIGENCE_REPORT_REGISTRY: dict[str, str] = {
    "evidence_map": "evidence_map.md",
    "contradiction_report": "contradiction_report.md",
    "research_timeline": "research_timeline.md",
    "literature_map": "literature_map.md",
    "method_comparison": "methods_comparison.md",
    "benchmark_analysis": "benchmark_analysis.md",
    "market_map": "market_map.md",
    "opportunity_map": "opportunity_map.md",
    "validation_candidates": "validation_candidates.md",
}

REASONING_REPORT_REGISTRY: dict[str, str] = {
    "hypotheses": "hypotheses.md",
    "assumptions": "assumptions.md",
    "decision_analysis": "decision_analysis.md",
    "methodology": "methodology.md",
    "experiment_plan": "experiment_plan.md",
    "evaluation_plan": "evaluation_plan.md",
    "validation_plan": "validation_plan.md",
}

REPORT_REGISTRY: dict[str, str] = {
    **DOMAIN_REPORT_REGISTRY,
    **INTELLIGENCE_REPORT_REGISTRY,
    **REASONING_REPORT_REGISTRY,
}

METRIC_REGISTRY: frozenset[str] = frozenset({
    "sources_discovered",
    "sources_accepted",
    "sources_rejected",
    "documents_fetched",
    "documents_failed",
    "search_failures",
    "evidence_created",
    "evidence_rejected",
    "unique_claims",
    "duplicate_claims",
    "contradictions",
    "gaps_open",
    "gaps_resolved",
    "new_evidence_this_iter",
    "new_claims_this_iter",
    "duplicate_claims_this_iter",
    "duplicate_rate",
    "rejection_rate",
    "queries_this_iter",
    "new_evidence_rate",
    "gap_resolution_rate",
    "source_diversity_domains",
    "llm_calls",
})

STOP_OPS: frozenset[str] = frozenset({"<=", "<", ">=", ">", "=="})

PROMPT_CALLER_KWARGS: dict[str, frozenset[str]] = {
    "problem_clarifier": frozenset({"raw_question", "mode", "mode_hint", "engine_guidance"}),
    "research_planner": frozenset({"objective", "mode", "mode_hint", "categories_hint", "engine_guidance"}),
    "_".join(("query", "generator")): frozenset({"branch_question", "required_evidence", "context", "n_queries"}),
    "evidence_extractor": frozenset({
        "source_title", "location", "page", "questions",
        "schema_hint", "domain_schema_hint", "chunk_text",
    }),
}
