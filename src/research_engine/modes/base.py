"""Research mode compatibility shim over the declarative Engine Pack loader.

Preserves the legacy ``ResearchMode``, ``ACADEMIC_MODE``, ``STARTUP_MODE``,
``MODES``, and ``get_mode(name)`` interface while delegating all definitions
to ``research_engine.engines.loader``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from research_engine.engines.loader import engine_names, get_engine
from research_engine.engines.manifest import EngineManifest


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


def _manifest_to_mode(manifest: EngineManifest) -> ResearchMode:
    return ResearchMode(
        name=manifest.name,
        display_name=manifest.display_name,
        branch_categories=manifest.branch_categories(),
        evidence_schema_hint=manifest.extraction.schema_hint,
        report_files=manifest.report_files(),
        source_preferences=list(manifest.planning.source_preferences),
    )


ACADEMIC_MODE = _manifest_to_mode(get_engine("academic"))
STARTUP_MODE = _manifest_to_mode(get_engine("startup"))

MODES: dict[str, ResearchMode] = {
    name: _manifest_to_mode(get_engine(name))
    for name in engine_names()
}


def _refresh_modes() -> None:
    MODES.clear()
    for name in engine_names():
        MODES[name] = _manifest_to_mode(get_engine(name))


def get_mode(name: str) -> ResearchMode:
    if name in MODES:
        return MODES[name]
    try:
        manifest = get_engine(name)
        mode = _manifest_to_mode(manifest)
        MODES[name] = mode
        return mode
    except Exception as exc:
        raise ValueError(f"unknown mode '{name}'; available: {list(MODES)}") from exc
