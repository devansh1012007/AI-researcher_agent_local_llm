"""Research mode abstraction.

A mode customizes: default branch categories, evidence schema hints, query strategy,
report set. Both academic and startup modes share the same core engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResearchMode:
    name: str
    display_name: str
    branch_categories: list[str]
    evidence_schema_hint: str
    report_files: list[str] = field(default_factory=list)
    source_preferences: list[str] = field(default_factory=lambda: ["web"])

    def default_reports(self) -> list[str]:
        return list(self.report_files)


ACADEMIC_MODE = ResearchMode(
    name="academic",
    display_name="Scientific / technical literature research",
    branch_categories=[
        "FOUNDATIONS", "CURRENT_STATE", "METHODS", "COMPETING_APPROACHES",
        "EVIDENCE", "BENCHMARKS", "LIMITATIONS", "CONTRADICTIONS",
        "APPLICATIONS", "OPEN_PROBLEMS",
    ],
    evidence_schema_hint=("research question; problem; method; model; dataset; "
                          "experimental setup; metrics; results; baselines; limitations; future work"),
    report_files=["problem.md", "research_plan.md", "info.md", "sources.md",
                  "gaps.md", "research_log.md", "literature_review.md"],
    source_preferences=["openalex", "arxiv", "crossref", "semantic_scholar", "web"],
)

STARTUP_MODE = ResearchMode(
    name="startup",
    display_name="Startup & market opportunity research",
    branch_categories=[
        "MARKET", "CUSTOMERS", "PAIN", "ALTERNATIVES", "COMPETITORS", "PRICING",
        "DISTRIBUTION", "REGULATIONS", "TECHNOLOGY", "FUNDING", "TIMING", "RISKS",
    ],
    evidence_schema_hint=("customer; segment; job-to-be-done; pain; current solution; competitor; "
                          "pricing; spending signal; market size; distribution; regulation; "
                          "technology shift; timing; funding signal; risk"),
    report_files=["problem.md", "research_plan.md", "info.md", "sources.md",
                  "gaps.md", "research_log.md", "startup_research.md"],
    source_preferences=["web"],
)

MODES = {m.name: m for m in (ACADEMIC_MODE, STARTUP_MODE)}


def get_mode(name: str) -> ResearchMode:
    if name not in MODES:
        raise ValueError(f"unknown mode '{name}'; available: {list(MODES)}")
    return MODES[name]
