"""Central research orchestrator.

The harness owns execution: state transitions, budgets, retries, checkpointing.
LLMs propose; the orchestrator decides and persists.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from research_engine.core.budget import Budget
from research_engine.core.config import AppConfig
from research_engine.core.state_machine import StateMachine
from research_engine.models.enums import (
    ProjectState, ReviewGate, StopReason, TaskStatus, TaskType,
)
from research_engine.models.project import ResearchMetrics, ResearchProject
from research_engine.models.task import Task
from research_engine.pipeline.clarification import ClarificationWorker
from research_engine.pipeline.documents import DocumentProcessor
from research_engine.pipeline.evidence import EvidenceWorker
from research_engine.pipeline.planning import PlannerWorker, QueryPlannerWorker, select_queries
from research_engine.pipeline.retrieval import RetrievalWorker
from research_engine.pipeline.routing import ProviderRegistry
from research_engine.reasoning.contradiction_detector import ContradictionDetector
from research_engine.reasoning.convergence import ConvergenceAnalyzer
from research_engine.reasoning.gap_detector import GapDetector
from research_engine.prompts.registry import record_versions
from research_engine.providers.llm.router import ModelRouter
from research_engine.storage.cache import KVCache
from research_engine.storage.database import Database
from research_engine.storage.events import EventLog
from research_engine.storage.repositories import Repositories
from research_engine.storage.workspace import Workspace

log = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, cfg: AppConfig, project: ResearchProject,
                 registry: ProviderRegistry | None = None):
        self.cfg = cfg
        self.project = project
        self.ws = Workspace(cfg.storage.data_dir, project.id)
        self.db = Database(self.ws.db_path)
        self.repos = Repositories(self.db)
        self.events = EventLog(self.ws.root)
        self.router = ModelRouter(cfg)
        self.registry = registry or build_default_registry(cfg)
        self.sm = StateMachine(self.repos)
        self.budget = Budget(cfg, project)
        self._stop_requested = False

    # ------------------------------------------------------------------ setup
    @classmethod
    def create_project(cls, cfg: AppConfig, question: str, mode: str | None = None) -> "Orchestrator":
        mode = mode or cfg.research.mode
        from research_engine.core.ids import project_id_from_question
        pid = project_id_from_question(question)
        project = ResearchProject(id=pid, question_raw=question.strip(), mode=mode)
        project.ensure_id()
        orch = cls(cfg, project)
        orch.project.config_snapshot = {
            "research": json.loads(cfg.research.model_dump_json()),
            "resources": json.loads(cfg.resources.model_dump_json()),
            "prompt_versions": record_versions(),
            "models": {r: getattr(cfg.models, r).model + "@" + getattr(cfg.models, r).provider
                       for r in ("extractor", "reasoning", "synthesis")},
        }
        orch.repos.projects.save(orch.project)
        orch.ws.project_json.write_text(json.dumps(
            json.loads(orch.project.model_dump_json()), indent=2, default=str))
        orch.events.record(pid, "project_created", "orchestrator",
                           metadata={"mode": mode}, human_line=f"\n[{_ts()}] PROJECT CREATED {pid}\nQuestion: {question}")
        return orch

    @classmethod
    def load(cls, cfg: AppConfig, project_id: str) -> "Orchestrator":
        ws = Workspace(cfg.storage.data_dir, project_id)
        db = Database(ws.db_path)
        repos = Repositories(db)
        project = repos.projects.get(project_id)  # type: ignore[assignment]
        if project is None:
            raise FileNotFoundError(f"project not found: {project_id}")
        return cls(cfg, project)

    def persist_checkpoint(self) -> None:
        self.project.updated_at = datetime.now(timezone.utc)
        self.repos.projects.save(self.project)
        self.ws.project_json.write_text(json.dumps(
            json.loads(self.project.model_dump_json()), indent=2, default=str))

    def request_stop(self) -> None:
        self._stop_requested = True

    # ------------------------------------------------------------------ main loop
    def run(self, max_iterations: int | None = None) -> ResearchProject:
        p = self.project
        try:
            if p.state == ProjectState.CREATED:
                self._phase_clarify()
            if p.state == ProjectState.CLARIFYING:
                self._phase_plan()
            if p.state == ProjectState.PLANNED:
                self._begin_iteration()
            guard = 0
            while p.state not in (ProjectState.CONVERGED, ProjectState.PAUSED,
                                  ProjectState.FAILED, ProjectState.CANCELLED,
                                  ProjectState.COMPLETED):
                guard += 1
                if guard > 200:
                    p.stop_reason = StopReason.FAILED
                    log.error("run-loop guard tripped; forcing stop")
                    break
                if self._stop_requested:
                    p.stop_reason = StopReason.USER_STOPPED
                    self.sm.transition(p, ProjectState.CONVERGED, "user requested stop")
                    break
                if p.state == ProjectState.SEARCHING:
                    self._phase_search_fetch_extract()
                elif p.state == ProjectState.ANALYZING_GAPS:
                    if not self._phase_analyze():
                        break
                else:  # FETCHING/EXTRACTING etc. are internal; anything else is terminal-ish
                    break
            if p.state == ProjectState.CONVERGED:
                if not self._review_gate(ReviewGate.BEFORE_FINAL_SYNTHESIS):
                    self.persist_checkpoint()
                    return p
                self._phase_synthesize()
        except Exception as exc:
            log.exception("orchestrator failure")
            p.stop_reason = StopReason.FAILED
            try:
                self.sm.transition(p, ProjectState.FAILED, str(exc)[:300])
            except ValueError:
                pass
            self.events.record(p.id, "fatal_error", "orchestrator", status="error", error=str(exc)[:500],
                               human_line=f"[{_ts()}] FATAL: {exc}")
            self.persist_checkpoint()
            raise
        self.persist_checkpoint()
        return p

    def resume(self) -> ResearchProject:
        """Resume a paused/interrupted project from its persisted state."""
        p = self.project
        gate = p.review_gate_pending
        if gate == ReviewGate.AFTER_PROBLEM_DEFINITION.value and p.state == ProjectState.PAUSED:
            self.sm.transition(p, ProjectState.PLANNED, "resumed after problem review")
        elif p.state == ProjectState.PAUSED:
            target = (ProjectState.SYNTHESIZING if gate == ReviewGate.BEFORE_FINAL_SYNTHESIS.value
                      and p.state in (ProjectState.CONVERGED,) else ProjectState.SEARCHING)
            if p.current_iteration == 0 or gate in (ReviewGate.AFTER_INITIAL_RESEARCH_PLAN.value,
                                                    ReviewGate.AFTER_PROBLEM_DEFINITION.value):
                target = ProjectState.SEARCHING
            self.sm.transition(p, target, f"resumed after gate {gate}")
        p.review_gate_pending = None
        self.repos.projects.save(p)
        if p.state != ProjectState.PLANNED and p.current_iteration == 0 and \
           p.state not in (ProjectState.COMPLETED, ProjectState.SYNTHESIZING):
            self._begin_iteration()
        return self.run()

    # ------------------------------------------------------------------ phases
    def _phase_clarify(self) -> None:
        p = self.project
        self.sm.transition(p, ProjectState.CLARIFYING, "start clarification")
        task = self._new_task(TaskType.CLARIFY_PROBLEM, 1.0)
        worker = ClarificationWorker(self.router.reasoning, self.repos)
        t0 = time.time()
        problem = worker.run(p.id, p.question_raw, p.mode)
        self._complete_task(task, {"problem_id": problem.id})
        self.events.record(p.id, "problem_clarified", "clarification", task.id,
                           duration_ms=(time.time() - t0) * 1000,
                           metadata={"subquestions": len(problem.subquestions),
                                     "assumptions": len(problem.assumptions)},
                           human_line=f"\n[{_ts()}] PROBLEM DEFINITION\nObjective: {problem.objective}\n"
                                      f"Subquestions: {len(problem.subquestions)}\n"
                                      + "\n".join(f"  - {a.text}" for a in problem.assumptions))
        if not self._review_gate(ReviewGate.AFTER_PROBLEM_DEFINITION):
            return
        # stays in CLARIFYING until the plan is generated (_phase_plan)

    def _phase_plan(self) -> None:
        p = self.project
        task = self._new_task(TaskType.GENERATE_RESEARCH_PLAN, 0.95)
        problem = self.repos.problems.all(p.id)[0]
        planner = PlannerWorker(self.router.reasoning, self.repos, p.mode)
        plan = planner.run(p.id, problem)
        qp = QueryPlannerWorker(self.router.reasoning, self.repos)
        queries = qp.run(p.id, plan, iteration=0)
        self._complete_task(task, {"branches": len(plan.branches), "queries": len(queries)})
        self.events.record(p.id, "plan_created", "planning", task.id,
                           metadata={"branches": [b.category for b in plan.branches]},
                           human_line=f"\n[{_ts()}] RESEARCH PLAN ({len(plan.branches)} branches)\n"
                                      + "\n".join(f"  [{b.category}] {b.question[:90]}"
                                                  for b in sorted(plan.branches, key=lambda x: -x.importance)))
        if not self._review_gate(ReviewGate.AFTER_INITIAL_RESEARCH_PLAN):
            return
        self.sm.transition(p, ProjectState.PLANNED, "plan created")

    def _begin_iteration(self) -> None:
        p = self.project
        p.current_iteration += 1
        p.budget.iterations_used = max(p.budget.iterations_used, p.current_iteration - 1)
        it = p.current_iteration
        self.events.record(p.id, "iteration_begin", "orchestrator", metadata={"iteration": it},
                           human_line=f"\n[{_ts()}] ITERATION {it}\n" + "-" * 40)
        self.sm.transition(p, ProjectState.SEARCHING, f"iteration {it} begins")

    def _phase_search_fetch_extract(self) -> None:
        p = self.project
        it = p.current_iteration
        # 1. queries: initial (iter 1) or follow-ups generated at end of prior cycle
        queries = self.repos.queries.all(p.id, "executed=0", ())
        if not queries:
            queries = self._generate_followups(it)
            if not queries:
                p.stop_reason = StopReason.NO_HIGH_VALUE_GAPS
                self.sm.transition(p, ProjectState.CONVERGED, "no further queries worth running")
                return
        selected = select_queries(queries, min(
            self.cfg.research.max_queries_per_iteration, self.budget.queries_left()))
        # 2. search
        retrieval = RetrievalWorker(self.cfg, self.repos, self.registry, 
                                    KVCache(f"{self.cfg.storage.data_dir}/_global/search_cache.sqlite"))
        executed_q, new_sources = retrieval.execute_queries(p.id, selected, self.budget.queries_left())
        self.budget.spend_query(len(executed_q))
        # 3. fetch + parse + chunk
        self.sm.transition(p, ProjectState.FETCHING, "search done")
        proc = self._make_document_processor()
        docs_before = self.repos.documents.count(p.id)
        documents = proc.process_sources(p.id, new_sources, self.budget.documents_left())
        fetched_now = self.repos.documents.count(p.id) - docs_before
        self.budget.spend_document(max(0, fetched_now))
        # 4. extract evidence
        self.sm.transition(p, ProjectState.EXTRACTING, "documents processed")
        problem = self.repos.problems.all(p.id)[0]
        questions = "\n".join([problem.research_question] + problem.subquestions[:10])
        ev_worker = EvidenceWorker(self.cfg, self.router.extractor, self.repos)
        new_ev, rejected_ct = ev_worker.extract_from_documents(
            p.id, documents, questions, iteration=it)
        self.sm.transition(p, ProjectState.VERIFYING, "extraction done")
        # claim consolidation includes quote verification already applied per-item
        new_claims, dup_claims = ev_worker.consolidate_claims(p.id, new_ev, it)
        useful_by_query: dict[str, int] = {}
        for e in new_ev:
            src = self.repos.sources.get(e.source_id)
            for qid in (src.query_ids if src else []):
                useful_by_query[qid] = useful_by_query.get(qid, 0) + 1
        for q in executed_q:
            q.useful_results = useful_by_query.get(q.id, 0)
            self.repos.queries.save(q)

        self.events.record(p.id, "cycle_complete", "retrieval",
                           metadata={"queries": len(executed_q), "sources": len(new_sources),
                                     "docs_fetched": max(0, fetched_now), "evidence": len(new_ev),
                                     "evidence_rejected": rejected_ct, "new_claims": new_claims},
                           status="ok" if new_sources else "empty",
                           human_line=(f"Queries executed: {len(executed_q)} | Sources found: {len(new_sources)} | "
                                       f"Docs parsed: {max(0, fetched_now)}\n"
                                       f"Evidence extracted: {len(new_ev)} (rejected: {rejected_ct}) | "
                                       f"New claims: {new_claims} (duplicates: {dup_claims})"))
        self.sm.transition(p, ProjectState.ANALYZING_GAPS, "verify done")

    def _phase_analyze(self) -> bool:
        """Returns True if another iteration should run."""
        p = self.project
        it = p.current_iteration
        gap_detector = GapDetector(self.router.reasoning, self.repos)
        problem = self.repos.problems.all(p.id)[0]
        plan = self.repos.plans.all(p.id)
        plan = plan[-1] if plan else None
        gaps = gap_detector.run(p.id, plan, problem, it)
        con_detector = ContradictionDetector(self.router.reasoning, self.repos)
        contradictions = con_detector.run(p.id)

        metrics = self._compute_metrics(it)
        self.repos.metrics.save(metrics)
        decision = ConvergenceAnalyzer(self.cfg, self.router.reasoning).evaluate(p, self.budget, {
            "objective": problem.objective, "iteration": it,
            "total_evidence": self.repos.evidence.count(p.id, "status!='REJECTED'"),
            "new_evidence": metrics.new_evidence_this_iter,
            "new_claims": metrics.new_claims_this_iter,
            "duplicate_rate": metrics.duplicate_rate,
            "high_importance_gaps": len([g for g in gaps if not g.resolved and g.importance >= 0.6]),
            "domains": metrics.source_diversity_domains,
        })
        high_gaps = len([g for g in gaps if not g.resolved and g.importance >= 0.6])
        self.events.record(p.id, "analysis_complete", "reasoning",
                           metadata={"gaps_open": len([g for g in gaps if not g.resolved]),
                                     "contradictions_new": len(contradictions),
                                     "stop_decision": decision.stop_reason.value if decision.should_stop else "continue"},
                           human_line=(f"Gaps open: {len([g for g in gaps if not g.resolved])} "
                                       f"(high-priority: {high_gaps}) | Contradictions total: "
                                       f"{self.repos.contradictions.count(p.id)}\n"
                                       + "\n".join(f"  GAP [{g.category.value}] {g.description[:100]}"
                                                   for g in sorted(gaps, key=lambda x: -x.importance)[:5])))
        p.budget.iterations_used = it
        if decision.should_stop:
            p.stop_reason = decision.stop_reason
            self.persist_checkpoint()
            if p.stop_reason in (StopReason.CONVERGED, StopReason.NO_HIGH_VALUE_GAPS):
                self.sm.transition(p, ProjectState.CONVERGED, decision.rationale)
            else:
                self.sm.transition(p, ProjectState.GENERATING_FOLLOWUPS, decision.rationale)
                self.sm.transition(p, ProjectState.CONVERGED, "budget stop -> synthesis")
            return False
        if it >= (self.cfg.research.max_iterations):
            p.stop_reason = StopReason.MAX_ITERATIONS
            self.sm.transition(p, ProjectState.CONVERGED, "max iterations reached")
            return False
        if it == 1:
            if not self._review_gate(ReviewGate.AFTER_FIRST_RESEARCH_CYCLE):
                return False
        self.sm.transition(p, ProjectState.GENERATING_FOLLOWUPS, "gaps remain")
        self._generate_followups(it)
        p.current_iteration += 1
        self.events.record(p.id, "iteration_begin", "orchestrator",
                           metadata={"iteration": p.current_iteration},
                           human_line=f"\n[{_ts()}] ITERATION {p.current_iteration}\n" + "-" * 40)
        self.sm.transition(p, ProjectState.SEARCHING, f"iteration {p.current_iteration} begins")
        return True

    def _generate_followups(self, it: int) -> list:
        """Create targeted follow-up queries from unresolved gaps + contradictions."""
        p = self.project
        plan = self.repos.plans.all(p.id)
        plan = plan[-1] if plan else None
        if plan is None:
            return []
        qp = QueryPlannerWorker(self.router.reasoning, self.repos)
        created = qp.run(p.id, plan, iteration=it, per_branch=3)
        # add gap-recommended and contradiction follow-up queries directly
        from research_engine.models.research import SearchQuery
        for g in self.repos.gaps.all(p.id, "resolved=0 AND importance>=0.55", ()):
            for rq in g.recommended_queries[:2]:
                q = SearchQuery(project_id=p.id, text=rq.text, branch=g.branch,
                                reason=f"gap {g.id}: {rq.reason}", kind="primary",
                                priority=g.importance, expected_information_gain=g.importance,
                                iteration=it)
                if not any(x.text == q.text for x in self.repos.queries.all(p.id)):
                    q.ensure_id()
                    self.repos.queries.save(q)
                    created.append(q)
        for c in self.repos.contradictions.all(p.id, "resolved=0", ()):
            if c.follow_up_query:
                q = SearchQuery(project_id=p.id, text=c.follow_up_query, reason=f"contradiction {c.id}",
                                kind="contradiction", priority=0.8,
                                expected_information_gain=0.8, iteration=it)
                if not any(x.text == q.text for x in self.repos.queries.all(p.id)):
                    q.ensure_id()
                    self.repos.queries.save(q)
                    created.append(q)
        self.events.record(p.id, "followup_queries_generated", "planning",
                           metadata={"count": len(created)},
                           human_line=f"Follow-up queries generated: {len(created)}"
                                      + ("".join(f"\n  + {q.text[:80]}" for q in created[:6])))
        return created

    def _phase_synthesize(self) -> None:
        from research_engine.reports.generator import ReportGenerator
        p = self.project
        self.sm.transition(p, ProjectState.SYNTHESIZING, "converged; generating reports")
        gen = ReportGenerator(self.cfg, self.router.synthesis, self.repos, self.ws)
        generated = gen.generate_all(p)
        self.sm.transition(p, ProjectState.COMPLETED, f"reports: {', '.join(generated)}")
        self.events.record(p.id, "reports_generated", "reports",
                           metadata={"reports": generated},
                           human_line=(f"\n[{_ts()}] RESEARCH {'CONVERGED' if p.stop_reason == StopReason.CONVERGED else 'STOPPED'} "
                                       f"({p.stop_reason.value if p.stop_reason else '?'})\n"
                                       f"Reports written to {self.ws.reports}:\n"
                                       + "\n".join(f"  - {r}" for r in generated)))

    # ------------------------------------------------------------------ helpers
    def _compute_metrics(self, it: int) -> ResearchMetrics:
        p = self.project
        m = ResearchMetrics(project_id=p.id, iteration=it)
        m.sources_accepted = self.repos.sources.count(p.id, "status='PARSED'")
        m.sources_rejected = self.repos.sources.count(p.id, "status='FAILED'")
        m.sources_discovered = self.repos.sources.count(p.id)
        m.documents_fetched = self.repos.documents.count(p.id, "status='PARSED'")
        m.documents_failed = self.repos.documents.count(p.id, "status!='PARSED'")
        m.evidence_created = self.repos.evidence.count(p.id)
        m.evidence_rejected = self.repos.evidence.count(p.id, "status='REJECTED'")
        m.unique_claims = self.repos.claims.count(p.id)
        m.contradictions = self.repos.contradictions.count(p.id)
        m.gaps_open = self.repos.gaps.count(p.id, "resolved=0")
        m.gaps_resolved = self.repos.gaps.count(p.id, "resolved=1")
        # per-iteration deltas come straight from iteration stamps on entities
        cur_ev_total = self.repos.evidence.count(p.id, "status!='REJECTED'")
        m.new_evidence_this_iter = self.repos.evidence.count(
            p.id, f"iteration={it} AND status!='REJECTED'")
        m.new_claims_this_iter = self.repos.claims.count(p.id, f"iteration={it}")
        m.duplicate_rate = round(self.repos.evidence.rejected_ratio(p.id), 3)
        m.new_evidence_rate = round(m.new_evidence_this_iter / max(1, cur_ev_total), 3)
        m.gap_resolution_rate = round(m.gaps_resolved / max(1, m.gaps_resolved + m.gaps_open), 3)
        parsed_sources = self.repos.sources.all(p.id, "status='PARSED'")
        domains = {s.domain for s in parsed_sources}
        m.source_diversity_domains = len(domains)
        tiers: dict[int, int] = {}
        for s in parsed_sources:
            tiers[s.source_tier] = tiers.get(s.source_tier, 0) + 1
        m.tier_distribution = {str(k): v for k, v in sorted(tiers.items())}
        m.llm_calls = (self.router.extractor.calls + self.router.reasoning.calls
                       + getattr(self.router.synthesis, "calls", 0))
        return m

    def _make_document_processor(self) -> DocumentProcessor:
        return DocumentProcessor(self.cfg, self.repos, self.ws)

    def _new_task(self, ttype: TaskType, priority: float) -> Task:
        t = Task(project_id=self.project.id, type=ttype, priority=priority,
                 iteration=self.project.current_iteration)
        t.ensure_id()
        self.repos.tasks.save(t)
        return t

    def _complete_task(self, task: Task, output: dict) -> None:
        task.status = TaskStatus.DONE
        task.output = output
        self.repos.tasks.save(task)

    def _review_gate(self, gate: ReviewGate) -> bool:
        """Returns True to continue. Pauses when review gates are enabled."""
        if not self.cfg.research.review_gates_enabled:
            return True
        p = self.project
        p.review_gate_pending = gate.value
        p.state = ProjectState.PAUSED
        self.persist_checkpoint()
        self.events.record(p.id, "review_gate", "orchestrator",
                           metadata={"gate": gate.value},
                           human_line=f"\n[{_ts()}] PAUSED AT REVIEW GATE: {gate.value}\n"
                                      "Run 'research resume' after reviewing.")
        log.info("paused at review gate %s", gate.value)
        return False


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def build_default_registry(cfg: AppConfig) -> ProviderRegistry:
    reg = ProviderRegistry()
    from research_engine.providers.academic.arxiv import ArxivProvider
    from research_engine.providers.academic.crossref import CrossrefProvider
    from research_engine.providers.academic.openalex import OpenAlexProvider
    from research_engine.providers.academic.semantic_scholar import SemanticScholarProvider
    from research_engine.providers.search.duckduckgo import DuckDuckGoProvider, SearxngProvider
    timeout = cfg.network.timeout_seconds
    reg.register_search("web", DuckDuckGoProvider(timeout=timeout))
    if cfg.search.searxng_base_url:
        reg.register_search("web_searxng", SearxngProvider(cfg.search.searxng_base_url, timeout))
    providers = {
        "openalex": OpenAlexProvider(timeout=timeout),
        "crossref": CrossrefProvider(timeout=timeout),
        "arxiv": ArxivProvider(timeout=timeout),
        "semantic_scholar": SemanticScholarProvider(cfg.search.semantic_scholar_api_key, timeout),
    }
    for name in cfg.search.academic_providers:
        if name in providers:
            reg.register_academic(name, providers[name])
    return reg
