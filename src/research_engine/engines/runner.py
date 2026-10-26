"""Declarative LoopRunner for EngineManifest loop specifications (Phase 3)."""
from __future__ import annotations

import logging
from typing import Any, Callable

from research_engine.engines.manifest import (
    EngineManifest,
    LoopStepSpec,
    StopConditionSpec,
)
from research_engine.engines.registry import STEP_TARGET_STATE
from research_engine.models.enums import ProjectState, ReviewGate, StopReason
from research_engine.models.project import ResearchMetrics, ResearchProject

log = logging.getLogger(__name__)


def evaluate_stop_conditions(
    conditions: list[StopConditionSpec],
    metrics: ResearchMetrics | dict[str, Any],
    iteration: int,
) -> tuple[bool, str]:
    """Evaluate declarative stop_when conditions against current iteration metrics."""
    for cond in conditions:
        if iteration < cond.after_iteration:
            continue
        actual = (
            metrics.get(cond.metric)
            if isinstance(metrics, dict)
            else getattr(metrics, cond.metric, None)
        )
        if actual is None:
            continue
        matched = False
        if cond.op == "<=":
            matched = actual <= cond.value
        elif cond.op == "<":
            matched = actual < cond.value
        elif cond.op == ">=":
            matched = actual >= cond.value
        elif cond.op == ">":
            matched = actual > cond.value
        elif cond.op == "==":
            matched = actual == cond.value
        if matched:
            return (
                True,
                f"stop_when: {cond.metric} ({actual}) {cond.op} {cond.value} at iteration {iteration}",
            )
    return False, ""


class LoopRunner:
    """Executes setup, per_iteration, and synthesis steps with cursor persistence and pause_after support."""

    def __init__(
        self,
        manifest: EngineManifest,
        project: ResearchProject,
        state_machine: Any,
        step_handlers: dict[str, Callable[[LoopStepSpec], bool | None]] | None = None,
        on_checkpoint: Callable[[], None] | None = None,
        metrics_provider: Callable[[int], ResearchMetrics | dict[str, Any] | None] | None = None,
        max_iterations: int = 3,
    ):
        self.manifest = manifest
        self.project = project
        self.sm = state_machine
        self.handlers = step_handlers or {}
        self.on_checkpoint = on_checkpoint or (lambda: None)
        self.metrics_provider = metrics_provider
        self.max_iterations = max_iterations

    def _save_cursor(
        self,
        phase: str,
        step_index: int,
        iteration: int,
        pending_pause: bool = False,
        gate: str | None = None,
    ) -> None:
        self.project.loop_cursor = {
            "phase": phase,
            "step_index": step_index,
            "iteration": iteration,
            "pending_pause": pending_pause,
            "gate": gate,
        }
        self.on_checkpoint()

    def _pause_at_step(
        self,
        phase: str,
        step_index: int,
        iteration: int,
        step_spec: LoopStepSpec,
    ) -> None:
        gate_name = step_spec.gate or f"AFTER_{step_spec.step.upper()}"
        self.project.review_gate_pending = gate_name
        self.sm.transition(self.project, ProjectState.PAUSED, f"pause_after step {step_spec.step}")
        self._save_cursor(phase, step_index, iteration, pending_pause=True, gate=gate_name)

    def _step_has_pause(self, phase: str, step_name: str) -> tuple[bool, LoopStepSpec | None]:
        steps = getattr(self.manifest.loop, phase, [])
        for idx, s in enumerate(steps):
            if s.step == step_name and s.pause_after:
                gate_name = s.gate or f"AFTER_{s.step.upper()}"
                if gate_name not in self.project.approved_gates:
                    return True, s
        return False, None

    def resume_cursor(self) -> None:
        """Advance cursor past a paused step so run() continues at the next step."""
        cur = dict(self.project.loop_cursor or {})
        if not cur.get("pending_pause"):
            return
        gate = cur.get("gate") or self.project.review_gate_pending
        if gate and gate not in self.project.approved_gates:
            self.project.approved_gates.append(gate)
        self.project.review_gate_pending = None
        phase = cur.get("phase", "setup")
        idx = int(cur.get("step_index", 0))
        it = int(cur.get("iteration", self.project.current_iteration))
        steps = getattr(self.manifest.loop, phase, [])
        if idx < len(steps):
            target_state = STEP_TARGET_STATE.get(steps[idx].step, ProjectState.SEARCHING)
        else:
            target_state = ProjectState.CONVERGED if phase == "synthesis" else ProjectState.SEARCHING
        if self.project.state == ProjectState.PAUSED:
            self.sm.transition(self.project, target_state, f"resumed from {phase}[{idx}]")
        self._save_cursor(phase, idx + 1, it, pending_pause=False, gate=None)

    def run_orchestrated(self, orch: Any, max_iterations: int | None = None) -> ResearchProject:
        """Execute an Orchestrator run driven by the manifest loop specification and cursor."""
        p = self.project
        if max_iterations is not None:
            orch.cfg.research.max_iterations = max_iterations
            self.max_iterations = max_iterations

        if p.state == ProjectState.CREATED:
            self._save_cursor("setup", 0, 0)
            orch._phase_clarify()
            if p.state == ProjectState.PAUSED:
                self._save_cursor("setup", 0, 0, pending_pause=True, gate=p.review_gate_pending)
                return p
            should_pause, step_spec = self._step_has_pause("setup", "clarify")
            if should_pause and step_spec is not None:
                self._pause_at_step("setup", 0, 0, step_spec)
                return p

        if p.state == ProjectState.CLARIFYING:
            self._save_cursor("setup", 2, 0)
            orch._phase_plan()
            if p.state == ProjectState.PAUSED:
                self._save_cursor("setup", 2, 0, pending_pause=True, gate=p.review_gate_pending)
                return p
            should_pause, step_spec = self._step_has_pause("setup", "plan")
            if should_pause and step_spec is not None:
                self._pause_at_step("setup", 2, 0, step_spec)
                return p

        if p.state == ProjectState.PLANNED:
            self._save_cursor("per_iteration", 0, max(1, p.current_iteration + 1))
            orch._begin_iteration()

        guard = 0
        while p.state not in (
            ProjectState.CONVERGED,
            ProjectState.PAUSED,
            ProjectState.FAILED,
            ProjectState.CANCELLED,
            ProjectState.COMPLETED,
        ):
            guard += 1
            if guard > 200:
                p.stop_reason = StopReason.FAILED
                log.error("run-loop guard tripped; forcing stop")
                break
            if orch._stop_requested:
                p.stop_reason = StopReason.USER_STOPPED
                self.sm.transition(p, ProjectState.CONVERGED, "user requested stop")
                break
            if orch._check_pause():
                self._save_cursor("per_iteration", 0, p.current_iteration, pending_pause=True, gate=p.review_gate_pending)
                return p
            if p.state == ProjectState.SEARCHING:
                self._save_cursor("per_iteration", 0, p.current_iteration)
                orch._phase_search_fetch_extract()
            elif p.state == ProjectState.ANALYZING_GAPS:
                self._save_cursor("per_iteration", 5, p.current_iteration)
                cont = orch._phase_analyze()
                if p.state == ProjectState.PAUSED:
                    self._save_cursor("per_iteration", 6, p.current_iteration, pending_pause=True, gate=p.review_gate_pending)
                    return p
                should_pause, step_spec = self._step_has_pause("per_iteration", "evaluate_convergence")
                if should_pause and step_spec is not None and p.state != ProjectState.CONVERGED:
                    self._pause_at_step("per_iteration", 6, p.current_iteration, step_spec)
                    return p
                if not cont:
                    break
            else:
                break

        if p.state == ProjectState.CONVERGED:
            self._save_cursor("synthesis", 0, p.current_iteration)
            if not orch._review_gate(ReviewGate.BEFORE_FINAL_SYNTHESIS):
                self._save_cursor("synthesis", 0, p.current_iteration, pending_pause=True, gate=p.review_gate_pending)
                return p
            orch._phase_synthesize()
            self._save_cursor("completed", 0, p.current_iteration, pending_pause=False)

        return p

    def run(self) -> ResearchProject:
        p = self.project
        cur = dict(p.loop_cursor or {})
        start_phase = cur.get("phase", "setup")
        start_idx = int(cur.get("step_index", 0))

        # 1. Setup phase
        if start_phase == "setup":
            for idx in range(start_idx, len(self.manifest.loop.setup)):
                step_spec = self.manifest.loop.setup[idx]
                self._save_cursor("setup", idx, 0)
                handler = self.handlers.get(step_spec.step)
                if handler is not None:
                    cont = handler(step_spec)
                    if p.state == ProjectState.PAUSED or cont is False:
                        self._save_cursor("setup", idx, 0, pending_pause=True, gate=p.review_gate_pending)
                        return p
                if step_spec.pause_after:
                    self._pause_at_step("setup", idx, 0, step_spec)
                    return p
            start_phase = "per_iteration"
            start_idx = 0
            if p.current_iteration == 0:
                p.current_iteration = 1

        # 2. Per-iteration loop
        if start_phase == "per_iteration":
            it = max(1, int(cur.get("iteration", p.current_iteration or 1)))
            p.current_iteration = it
            step_start = start_idx
            while it <= self.max_iterations:
                p.current_iteration = it
                converged = False
                for idx in range(step_start, len(self.manifest.loop.per_iteration)):
                    step_spec = self.manifest.loop.per_iteration[idx]
                    self._save_cursor("per_iteration", idx, it)
                    handler = self.handlers.get(step_spec.step)
                    if handler is not None:
                        cont = handler(step_spec)
                        if p.state == ProjectState.PAUSED:
                            self._save_cursor("per_iteration", idx, it, pending_pause=True, gate=p.review_gate_pending)
                            return p
                        if cont is False and step_spec.step == "evaluate_convergence":
                            converged = True
                    if step_spec.pause_after:
                        self._pause_at_step("per_iteration", idx, it, step_spec)
                        return p
                    if converged:
                        break

                if not converged and self.metrics_provider is not None and self.manifest.loop.stop_when:
                    m = self.metrics_provider(it)
                    if m is not None:
                        matched, reason = evaluate_stop_conditions(self.manifest.loop.stop_when, m, it)
                        if matched:
                            p.stop_reason = p.stop_reason or StopReason.CONVERGED
                            self.sm.transition(p, ProjectState.CONVERGED, reason)
                            converged = True

                if converged or p.state == ProjectState.CONVERGED:
                    break
                if it >= self.max_iterations:
                    p.stop_reason = p.stop_reason or StopReason.MAX_ITERATIONS
                    self.sm.transition(p, ProjectState.CONVERGED, "max iterations reached")
                    break
                it += 1
                step_start = 0

            start_phase = "synthesis"
            start_idx = 0

        # 3. Synthesis phase
        if start_phase == "synthesis":
            for idx in range(start_idx, len(self.manifest.loop.synthesis)):
                step_spec = self.manifest.loop.synthesis[idx]
                self._save_cursor("synthesis", idx, p.current_iteration)
                handler = self.handlers.get(step_spec.step)
                if handler is not None:
                    cont = handler(step_spec)
                    if p.state == ProjectState.PAUSED or cont is False:
                        self._save_cursor("synthesis", idx, p.current_iteration, pending_pause=True, gate=p.review_gate_pending)
                        return p
                if step_spec.pause_after:
                    self._pause_at_step("synthesis", idx, p.current_iteration, step_spec)
                    return p

        self._save_cursor("completed", 0, p.current_iteration, pending_pause=False)
        return p
