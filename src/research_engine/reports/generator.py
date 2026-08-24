"""Report generation: SQLite state -> human-readable Markdown.

info.md is DERIVED from the database, never the primary store.
Every important claim links back to evidence IDs and source URLs (traceability chain:
report -> claim id -> evidence id -> document -> source URL).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from research_engine.core.config import AppConfig
from research_engine.providers.llm.base import LLMProvider
from research_engine.reports.synthesis import Synthesizer, build_findings_context, deterministic_findings
from research_engine.storage.repositories import Repositories
from research_engine.storage.workspace import Workspace

log = logging.getLogger(__name__)


class ReportGenerator:
    def __init__(self, cfg: AppConfig, provider: LLMProvider | None,
                 repos: Repositories, ws: Workspace):
        self.cfg = cfg
        self.repos = repos
        self.ws = ws
        self.synth = Synthesizer(provider)

    def generate_all(self, project) -> list[str]:
        written = []
        for name, fn in [
            ("problem.md", self.write_problem),
            ("research_plan.md", self.write_plan),
            ("info.md", self.write_info),
            ("sources.md", self.write_sources),
            ("gaps.md", self.write_gaps),
        ]:
            path = fn(project)
            if path:
                written.append(name)
        if project.mode == "academic":
            if self.write_literature_review(project):
                written.append("literature_review.md")
        elif project.mode == "startup":
            if self.write_startup_research(project):
                written.append("startup_research.md")
        # research_log.md is maintained incrementally by EventLog; ensure header exists
        log_path = self.ws.reports / "research_log.md"
        if not log_path.exists():
            log_path.write_text(f"# Research Log — {project.id}\n")
            written.append("research_log.md")
        # structured exports for downstream tools (vector indexing, analysis)
        pid = project.id
        self.ws.export_jsonl("evidence",
                             [e.model_dump() for e in self.repos.evidence.all(pid)])
        self.ws.export_jsonl("claims",
                             [c.model_dump() for c in self.repos.claims.all(pid)])
        self.ws.export_jsonl("sources",
                             [s.model_dump() for s in self.repos.sources.all(pid)])
        return written

    def _write(self, name: str, content: str):
        path = self.ws.report_path(name)
        path.write_text(content, encoding="utf-8")
        return path

    # ------------------------------------------------------------------ reports
    def write_problem(self, project) -> str:
        problems = self.repos.problems.all(project.id)
        p = problems[0] if problems else None
        lines = [f"# Problem Definition", "",
                 f"**Project:** `{project.id}`  ",
                 f"**Raw question:** {project.question_raw}", ""]
        if p is None:
            lines.append("(problem definition not generated)")
            return str(self._write("problem.md", "\n".join(lines)))
        lines += [
            f"## Objective", p.objective, "",
            f"## Research Question", p.research_question, "",
            "## Scope",
            *[f"- {s}" for s in (p.scope or ["(not specified)"])], "",
            "## Out of Scope",
            *[f"- {s}" for s in (p.out_of_scope or ["(not specified)"])], "",
            "## Subquestions",
            *[f"{i}. {s}" for i, s in enumerate(p.subquestions or ["(none)"], 1)], "",
            "## Constraints",
            *[f"- {c}" for c in (p.constraints + [x for x in [p.time_horizon and f"time horizon: {p.time_horizon}",
                                                               p.geographic_scope and f"geography: {p.geographic_scope}"] if x] or ["(none)"])],
            "", "## Evaluation Criteria",
            *[f"- {c}" for c in (p.evaluation_criteria or ["(none)"])], "",
        ]
        if p.ambiguities:
            lines += ["## Ambiguities Identified", *[f"- {a}" for a in p.ambiguities], ""]
        if p.assumptions:
            lines += ["## Assumptions (explicit; user-overridable)", ""]
            for a in p.assumptions:
                flag = " [OVERRIDDEN]" if a.overridden else ""
                lines.append(f"- **{a.text}**{flag} — rationale: {a.rationale}")
        return str(self._write("problem.md", "\n".join(lines)))

    def write_plan(self, project) -> str:
        plans = self.repos.plans.all(project.id)
        plan = plans[-1] if plans else None
        queries = self.repos.queries.all(project.id)
        lines = [f"# Research Plan", ""]
        if plan is None:
            lines.append("(plan not generated)")
            return str(self._write("research_plan.md", "\n".join(lines)))
        lines.append(f"Objective: {plan.objective}")
        lines.append("")
        branches = sorted(plan.branches, key=lambda b: -b.importance)
        claims = self.repos.claims.all(project.id)
        evidence = {e.id: e for e in self.repos.evidence.all(project.id)}
        for b in branches:
            n_ev = len([e for e in evidence.values()
                        if e.status.value != "REJECTED" and any(
                            c.branch == b.id for c in claims if e.id in c.supported_by)])
            status = next((c for c in claims if False), None)
            lines.append(f"## [{b.category}] {b.question}")
            lines.append(f"- importance: {b.importance:.2f}; branch id: `{b.id}`; status: {b.status}")
            lines.append(f"- required evidence: {b.required_evidence or '(unspecified)'}")
            lines.append(f"- source preferences: {', '.join(b.source_preferences) or 'default routing'}")
            lines.append("")
        lines += ["## Queries Executed", "",
                  "| query | kind | results | useful | gain | reason |", "|---|---|---|---|---|---|"]
        for q in sorted(queries, key=lambda x: -x.expected_information_gain)[:60]:
            lines.append(f"| {q.text[:80]} | {q.kind} | {q.results_count} | {q.useful_results} "
                         f"| {q.expected_information_gain:.2f} | {q.reason[:60]} |")
        return str(self._write("research_plan.md", "\n".join(lines)))

    def write_info(self, project) -> str:
        claims = self.repos.claims.all(project.id)
        evidence = {e.id: e for e in self.repos.evidence.all(project.id)}
        contradictions = self.repos.contradictions.all(project.id)
        gaps = [g for g in self.repos.gaps.all(project.id) if not g.resolved]
        sources = self.repos.sources.all(project.id, "status='PARSED'")
        problems = self.repos.problems.all(project.id)
        problem = problems[0] if problems else None
        metrics = sorted(self.repos.metrics.all(project.id), key=lambda m: m.iteration)
        last = metrics[-1] if metrics else None

        ctx = {
            "objective": problem.objective if problem else project.question_raw,
            "research_question": problem.research_question if problem else project.question_raw,
            "scope_and_assumptions": _scope_block(problem),
            "findings_input": build_findings_context(claims, evidence),
            "contradictions_input": "\n".join(
                f"- {c.statement_a}  VS  {c.statement_b} — possible explanation: {c.explanation}"
                for c in contradictions) or "(none)",
            "gaps_input": "\n".join(f"- [{g.category.value}] {g.description}" for g in gaps[:25]) or "(none)",
            "source_summary": f"{len(sources)} parsed sources; tier distribution: "
                              f"{_tier_hist(sources)}; domains: {len({s.domain for s in sources})}",
        }
        sections = {}
        for section in ("Executive Summary", "Key Findings", "Important Numbers",
                        "Contradictions", "Unknowns and Blind Spots"):
            md = self.synth.write_section(section, ctx)
            if md:
                sections[section] = md

        stop_note = ""
        if project.stop_reason and project.stop_reason != project.stop_reason.CONVERGED:
            stop_note = (f"\n> **Note:** research ended due to `{project.stop_reason.value}`; "
                         "conclusions may be budget-limited.\n")

        lines = [f"# Research Report — info.md", "",
                 f"*Generated {datetime.now(timezone.utc).isoformat()}* · "
                 f"project `{project.id}` · mode `{project.mode}`", stop_note]

        lines.append(f"\n## Executive Summary\n")
        lines.append(sections.get("Executive Summary") or _fallback_summary(project, problem))
        lines.append(f"\n## Scope and Assumptions\n")
        lines.append(_scope_block(problem))
        lines.append(f"\n## Methodology\n")
        lines.append(_methodology_block(project, last, self.cfg))

        lines.append("\n## Key Findings\n")
        lines.append(sections.get("Key Findings") or deterministic_findings(claims, evidence))

        numeric = [e for e in evidence.values() if e.numbers and e.status.value != "REJECTED"]
        lines.append("\n## Important Numbers / Measurements\n")
        if numeric:
            lines += ["| number | metric | period | source | evidence |",
                      "|---|---|---|---|---|"]
            for e in numeric[:30]:
                for n in e.numbers[:3]:
                    lines.append(f"| {n.value_raw} {n.unit}{' ' + n.currency if n.currency else ''} "
                                 f"| {n.metric} | {n.period or '?'} "
                                 f"| [{e.source_title[:40]}]({e.source_url}) "
                                 f"| [{e.id}] |")
            lines.append("")
        else:
            lines.append("_No verified numerical evidence collected._\n")

        lines.append("\n## Contradictions (preserved, not resolved)\n")
        if contradictions:
            for c in contradictions:
                lines.append(f"### {c.id}")
                lines.append(f"- A ({c.claim_a_id}): {c.statement_a}")
                lines.append(f"- B ({c.claim_b_id}): {c.statement_b}")
                lines.append(f"- Possible explanation: {c.explanation}")
                lines.append(f"- Source quality note: {c.source_quality_note}")
                lines.append(f"- Suggested follow-up: *{c.follow_up_query}*")
                lines.append("")
        else:
            lines.append("_No contradictions detected._\n")

        lines.append("\n## Unresolved Questions & Blind Spots\n")
        if gaps:
            for g in sorted(gaps, key=lambda x: -x.importance)[:20]:
                lines.append(f"- **[{g.category.value}]** {g.description} *(importance {g.importance:.2f})*")
        else:
            lines.append("_No open gaps recorded._\n")

        lines.append("\n## Evidence Quality\n")
        total = len(evidence)
        rej = len([e for e in evidence.values() if e.status.value == "REJECTED"])
        tiers = _tier_hist(list(evidence.values()))
        lines.append(f"- evidence items stored: {total} (rejected by validation: {rej})")
        lines.append(f"- evidence source-tier histogram: {tiers}")
        lines.append(f"- distinct domains among parsed sources: {len({s.domain for s in sources})}")
        if last:
            lines.append(f"- LLM calls used: {last.llm_calls}; iterations: {last.iteration}")

        lines.append("\n## Traceability\n")
        lines.append("Claim IDs (`clm_*`) link to evidence IDs (`ev_*`); each evidence item stores "
                     "`document_id`, `source_id`, quote and location. Query the CLI (`research inspect`) "
                     "or the SQLite DB for the full chain.\n")

        lines.append("\n## Full Source List\n")
        lines.append("See `sources.md`.")
        return str(self._write("info.md", "\n".join(lines)))

    def write_sources(self, project) -> str:
        sources = self.repos.sources.all(project.id)
        accepted = [s for s in sources if s.content_status == "PARSED"]
        rejected = [s for s in sources if s.content_status in ("FAILED", "BLOCKED")]
        dupes = [s for s in sources if s.content_status == "DUPLICATE"]
        lines = [f"# Sources", "",
                 f"Parsed/accepted: **{len(accepted)}** · failed: **{len(rejected)}** · "
                 f"duplicates skipped: **{len(dupes)}**", ""]
        lines += ["## Accepted Sources", "",
                  "| id | tier | type | title | domain | published | url |",
                  "|---|---|---|---|---|---|---|"]
        for s in sorted(accepted, key=lambda x: (x.source_tier, x.title)):
            lines.append(f"| `{s.id}` | {s.source_tier} | {s.source_type.value} | "
                         f"{s.title[:70]} | {s.domain[:24]} | {s.publication_date or '?'} "
                         f"| {s.url[:80]} |")
        if rejected:
            lines += ["", "## Rejected / Failed (audit trail)", "",
                      "| url | status | reason |", "|---|---|---|"]
            for s in rejected[:80]:
                lines.append(f"| {s.url[:70]} | {s.content_status} | {s.rejected_reason[:50]} |")
        if dupes:
            lines += ["", "## Duplicates Skipped", ""]
            for s in dupes[:40]:
                lines.append(f"- {s.url[:90]} — {s.rejected_reason}")
        return str(self._write("sources.md", "\n".join(lines)))

    def write_gaps(self, project) -> str:
        gaps = self.repos.gaps.all(project.id)
        contradictions = self.repos.contradictions.all(project.id)
        open_gaps = sorted([g for g in gaps if not g.resolved], key=lambda g: -g.importance)
        resolved = [g for g in gaps if g.resolved]
        lines = [f"# Gaps & Contradictions", "",
                 f"Open: **{len(open_gaps)}** · resolved: **{len(resolved)}** · "
                 f"contradictions: **{len(contradictions)}**", ""]
        lines += ["## Open Gaps", ""]
        for g in open_gaps:
            lines.append(f"### {g.id} — [{g.category.value}] severity={g.severity.value}")
            lines.append(f"{g.description}")
            lines.append(f"- importance: {g.importance:.2f}")
            lines.append(f"- evidence needed: {g.evidence_needed or '(unspecified)'}")
            for rq in g.recommended_queries:
                lines.append(f"- suggested query: *{rq.text}* ({rq.reason[:60]})")
            lines.append("")
        if resolved:
            lines += ["## Resolved Gaps", ""]
            for g in resolved:
                lines.append(f"- ~~{g.description[:120]}~~ (resolved iteration {g.iteration_resolved})")
        if contradictions:
            lines += ["## Contradictions", ""]
            for c in contradictions:
                lines.append(f"- `{c.id}`: \"{c.statement_a[:100]}\" vs \"{c.statement_b[:100]}\" "
                             f"— explanation: {c.explanation[:150]}")
        return str(self._write("gaps.md", "\n".join(lines)))

    def write_literature_review(self, project) -> str:
        claims = self.repos.claims.all(project.id)
        evidence = {e.id: e for e in self.repos.evidence.all(project.id)}
        papers = [s for s in self.repos.sources.all(project.id, "status='PARSED'")
                  if s.source_type.value == "research_paper"]
        ctx = _base_ctx(self.repos, project)
        ctx["findings_input"] = build_findings_context(claims, evidence)
        md = self.synth.write_section("Literature Review (foundational work, major directions, "
                                      "method comparison, datasets/benchmarks, recent developments, "
                                      "open problems)", ctx)
        if md is None:
            md = _deterministic_lit_review(papers, claims, evidence)
        body = (f"# Literature Review\n\nPapers parsed: {len(papers)}\n\n" + md + "\n\n"
                + "### Paper Landscape\n\n"
                + "\n".join(f"- **{p.title[:110]}** ({p.publication_date or 'n.d.'}, citations="
                            f"{p.citation_count if p.citation_count is not None else '?'}) — {p.url}"
                            for p in sorted(papers, key=lambda x: -(x.citation_count or 0))[:40]))
        self._write("literature_review.md", body)
        return True

    def write_startup_research(self, project) -> str:
        claims = self.repos.claims.all(project.id)
        evidence = {e.id: e for e in self.repos.evidence.all(project.id)}
        ctx = _base_ctx(self.repos, project)
        ctx["findings_input"] = build_findings_context(claims, evidence)
        md = self.synth.write_section(
            "Startup Research (market structure, customer segments, pain points, existing "
            "alternatives, competitors, market signals, opportunity areas, risks, evidence gaps, "
            "potential validation experiments). Carefully separate OBSERVED EVIDENCE from INFERENCE.",
            ctx)
        if md is None:
            md = deterministic_findings(claims, evidence)
        self._write("startup_research.md", "# Startup Research\n\n" + md + "\n")
        return True


# ---------------------------------------------------------------------------
def _base_ctx(repos: Repositories, project) -> dict:
    from research_engine.reports.synthesis import build_findings_context as _b  # noqa: F811
    problems = repos.problems.all(project.id)
    problem = problems[0] if problems else None
    claims = repos.claims.all(project.id)
    evidence = {e.id: e for e in repos.evidence.all(project.id)}
    contradictions = repos.contradictions.all(project.id)
    gaps = [g for g in repos.gaps.all(project.id) if not g.resolved]
    sources = repos.sources.all(project.id, "status='PARSED'")
    return {
        "objective": problem.objective if problem else project.question_raw,
        "research_question": problem.research_question if problem else project.question_raw,
        "scope_and_assumptions": _scope_block(problem),
        "findings_input": "",
        "contradictions_input": "\n".join(f"- {c.statement_a} vs {c.statement_b}: {c.explanation}"
                                          for c in contradictions) or "(none)",
        "gaps_input": "\n".join(f"- [{g.category.value}] {g.description}" for g in gaps[:25]) or "(none)",
        "source_summary": f"{len(sources)} sources; tiers {_tier_hist(sources)}",
    }


def _scope_block(problem) -> str:
    if problem is None:
        return "(not recorded)"
    parts = [f"**Scope:** {', '.join(problem.scope) or 'unspecified'}",
             f"**Out of scope:** {', '.join(problem.out_of_scope) or 'unspecified'}"]
    if problem.assumptions:
        parts.append("**Assumptions:**\n" + "\n".join(
            f"- {a.text} ({'overridden' if a.overridden else a.rationale})"
            for a in problem.assumptions))
    return "\n\n".join(parts)


def _methodology_block(project, last_metric, cfg) -> str:
    snap = project.config_snapshot or {}
    models = snap.get("models", {})
    lines = [
        f"- Mode: `{project.mode}`; engine v{project.engine_version}",
        f"- Models: extractor={models.get('extractor','?')}, reasoning={models.get('reasoning','?')}, "
        f"synthesis={models.get('synthesis','?')}",
        f"- Iterations run: {project.current_iteration}; stop reason: "
        f"`{project.stop_reason.value if project.stop_reason else 'n/a'}`",
        f"- Budget at end: {_budget_snapshot(project)}",
        "- Pipeline: clarify → plan → query generation → multi-source search → fetch+parse → "
        "chunked extraction → quote verification → dedup → gap/contradiction analysis → convergence "
        "→ synthesis. Every extracted quote was verified against its chunk text.",
    ]
    if snap.get("prompt_versions"):
        lines.append(f"- Prompt versions: {snap['prompt_versions']}")
    return "\n".join(lines)


def _budget_snapshot(project) -> str:
    b = project.budget
    return (f"queries={b.queries_used}, documents={b.documents_used}, "
            f"llm_calls={b.llm_calls_used}, bytes={b.bytes_downloaded}")


def _tier_hist(items) -> dict:
    out: dict[int, int] = {}
    for it in items:
        t = getattr(it, "source_tier", None)
        if t is not None:
            out[t] = out.get(t, 0) + 1
    return dict(sorted(out.items()))


def _fallback_summary(project, problem) -> str:
    q = problem.research_question if problem else project.question_raw
    return (f"This report addresses: **{q}**\n\n"
            "_Note: synthesis model unavailable; findings below are assembled directly from "
            "validated evidence records without narrative summarization._")


def _deterministic_lit_review(papers, claims, evidence) -> str:
    if not papers:
        return "_No research papers were successfully retrieved and parsed._\n"
    lines = ["### Papers Retrieved\n"]
    for p in sorted(papers, key=lambda x: -(x.citation_count or 0))[:30]:
        lines.append(f"- **{p.title[:120]}** — {p.author[:60]} — {p.publication_date or 'n.d.'} — {p.url}")
    lines.append("\n### Findings From Literature (deterministic assembly)\n")
    facts = [c for c in claims if c.kind.value == "FACT" and c.supported_by]
    for c in facts[:30]:
        ev_ids = ", ".join(eid for eid in c.supported_by[:3])
        lines.append(f"- {c.text} (confidence {c.confidence:.2f}; evidence: {ev_ids})")
    return "\n".join(lines)
