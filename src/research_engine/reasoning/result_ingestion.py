"""Result ingestion + hypothesis evaluation + knowledge update (spec #56-#62).

Manual result ingestion first: the user provides observations/metrics; the system
classifies the outcome against PRE-REGISTERED criteria, converts results into
first-class evidence with distinct provenance, updates hypothesis state, and
propagates confidence changes to dependent claims/opportunities.
"""
from __future__ import annotations

import logging

from research_engine.models.enums import EvidenceStatus, SourceType
from research_engine.models.evidence import Evidence
from research_engine.models.reasoning import Experiment, ExperimentResult
from research_engine.storage.repositories import Repositories
from research_engine.storage.reasoning_repos import ReasoningRepos

log = logging.getLogger(__name__)


class ResultIngestor:
    def __init__(self, repos: Repositories, rrepos: ReasoningRepos):
        self.repos = repos
        self.rrepos = rrepos

    def ingest(self, project_id: str, experiment_id: str,
               observations: list[str], metrics: dict | None = None,
               raw_notes: str = "", limitations: list[str] | None = None,
               interpretation_hint: str = "") -> dict:
        """Ingest a completed experiment's results and evaluate the hypothesis.

        The verdict is determined by comparing reported metrics against the
        methodology's PRE-DEFINED success/failure conditions wherever possible.
        The user may override the verdict explicitly; overrides are recorded as such.
        """
        exp = self.rrepos.experiments.get(experiment_id)
        if exp is None:
            raise ValueError(f"experiment not found: {experiment_id}")
        meth = self.rrepos.methodologies.get(exp.methodology_id)
        h = self.rrepos.hypotheses.get(exp.hypothesis_id)

        # 1. persist raw result — interpretation never overwrites raw data (#56)
        result = ExperimentResult(
            project_id=project_id, experiment_id=exp.id, hypothesis_id=exp.hypothesis_id,
            observations=[o[:500] for o in observations][:20],
            metrics=dict(metrics or {}),
            raw_notes=raw_notes[:4000],
            limitations=[lim[:200] for lim in (limitations or [])][:6],
            source_kind="user_provided",
        )
        result.ensure_id()
        self.rrepos.experiment_results.save(result)

        # 2. classify against predefined criteria
        verdict, reasoning = self._classify(meth, observations, metrics or {},
                                            interpretation_hint)

        # 3. update experiment lifecycle
        exp.status = "RESULT_INGESTED"
        self.rrepos.experiments.save(exp)

        # 4. convert into first-class evidence with EXPERIMENT_RESULT provenance (#58/#59)
        ev = Evidence(
            project_id=project_id,
            claim_text=(f"Experiment [{exp.title[:80]}] produced: "
                        f"{'; '.join(observations[:2]) if observations else raw_notes[:120]}"),
            quote=(raw_notes[:300] or "; ".join(observations)[:300] or
                   f"metrics={metrics}"),
            source_type=SourceType.EXPERIMENT_RESULT if hasattr(SourceType, "EXPERIMENT_RESULT")
                        else SourceType.OTHER,
            source_tier=1,   # controlled first-hand evidence; provenance kind distinguishes it
            confidence=0.85,
            source_url="", source_title=f"experiment:{exp.id}",
            status=EvidenceStatus.SUPPORTED,
            validation_notes="user-provided experiment result; not web-verifiable",
        )
        ev.ensure_id()
        self.repos.evidence.save(ev)
        self.repos.db.fts_index(ev.id, project_id, "evidence",
                                f"{ev.claim_text} {ev.quote}")

        # 5. attach to hypothesis with stance + update state
        stance = ("strongly_supports" if verdict == "supports" else
                  "strongly_contradicts" if verdict == "contradicts" else "neutral")
        if h is not None:
            if verdict == "supports":
                h.supporting_evidence.append(ev.id)
            elif verdict == "contradicts":
                h.contradicting_evidence.append(ev.id)
            new_status = {"supports": "SUPPORTED", "contradicts": "CONTRADICTED",
                          "inconclusive": "TESTING"}.get(verdict, h.status)
            reason_note = f"experiment {exp.id}: {verdict}"
            if new_status != h.status:
                # walk the legal transition path (state machine is never bypassed)
                from research_engine.reasoning.hypothesis_engine import ALLOWED_HYPO_TRANSITIONS
                path = _walk_path(h.status, new_status)
                if path is None:
                    log.warning("no legal path %s -> %s; leaving state", h.status, new_status)
                else:
                    for step in path:
                        h.status = step
                    reason_note += f" (via {'->'.join(path)})"
            # qualitative confidence update with explicit reasoning (#61/#62) — no fake Bayes
            delta = {"supports": 0.2, "contradicts": -0.35, "inconclusive": 0.0}[verdict]
            old_conf = h.confidence
            h.confidence = round(min(1.0, max(0.0, h.confidence + delta)), 3)
            h.scores["last_result"] = {
                "result_id": result.id, "verdict": verdict, "stance": stance,
                "reasoning": reason_note[:300],
                "confidence_change": round(h.confidence - old_conf, 3),
            }
            self.rrepos.hypotheses.save(h)
            exp.status = "EVALUATED"
            self.rrepos.experiments.save(exp)

        return {
            "result_id": result.id, "evidence_id": ev.id,
            "verdict": verdict, "reasoning": reasoning,
            "hypothesis_status": h.status if h else None,
            "confidence_after": h.confidence if h else None,
        }

    @staticmethod
    def _classify(meth, observations: list[str], metrics: dict,
                  interpretation_hint: str) -> tuple[str, str]:
        """Prefer pre-registered criteria; fall back to explicit hint; else inconclusive."""
        text = " ".join(observations).lower() + " " + str(metrics).lower() + \
               " " + (interpretation_hint or "").lower()

        if meth is not None and meth.success_condition:
            success_kw = _keywords(meth.success_condition)
            failure_kw = _keywords(meth.failure_condition or "")
            success_hits = sum(1 for k in success_kw if k in text)
            failure_hits = sum(1 for k in failure_kw if k in text)
            if success_hits > failure_hits and success_hits > 0:
                return "supports", ("matches pre-registered success condition: "
                                    f"'{meth.success_condition[:100]}'")
            if failure_hits > success_hits and failure_hits > 0:
                return "contradicts", ("matches pre-registered failure condition: "
                                       f"'{(meth.failure_condition or '')[:100]}'")
        if interpretation_hint:
            hint = interpretation_hint.lower()
            if any(k in hint for k in ("support", "confirm", "success", "validated")):
                return "supports", "user-classified as supportive (override recorded)"
            if any(k in hint for k in ("contradict", "fail", "refut", "falsif")):
                return "contradicts", "user-classified as contradicting (override recorded)"
        return "inconclusive", ("could not match results against pre-registered criteria; "
                                "human judgment required")


def _keywords(condition: str) -> list[str]:
    import re
    stop = {"the", "and", "with", "over", "across", "from", "that", "this", "into",
            "condition", "results", "metric"}
    words = [w for w in re.findall(r"[a-z]{4,}", condition.lower()) if w not in stop]
    return words[:8]


def _walk_path(start: str, goal: str) -> list[str] | None:
    """BFS through ALLOWED_HYPO_TRANSITIONS; results may advance a young hypothesis."""
    from research_engine.reasoning.hypothesis_engine import ALLOWED_HYPO_TRANSITIONS
    if start == goal:
        return []
    from collections import deque
    q = deque([(start, [])])
    seen = {start}
    while q:
        state, path = q.popleft()
        for nxt in sorted(ALLOWED_HYPO_TRANSITIONS.get(state, set())):
            if nxt == goal:
                return path + [nxt]
            if nxt not in seen and nxt not in ("ABANDONED", "SUPERSEDED", "FALSIFIED"):
                seen.add(nxt)
                q.append((nxt, path + [nxt]))
    return None


def approve_experiment(rrepos: ReasoningRepos, project_id: str, experiment_id: str,
                       approved: bool, note: str = "") -> Experiment:
    """Human approval gate (spec #77): DESIGNED -> READY_FOR_HUMAN_APPROVAL ->
    READY_FOR_EXECUTION (only after explicit approval)."""
    x = rrepos.experiments.get(experiment_id)
    if x is None:
        raise ValueError(f"experiment not found: {experiment_id}")
    if x.status == "DESIGNED":
        x.status = "READY_FOR_HUMAN_APPROVAL"
    elif x.status == "READY_FOR_HUMAN_APPROVAL":
        if not approved:
            x.status = "DESIGNED"
            x.decision_note = f"[rejected by user] {note}"[:200]
        else:
            x.status = "READY_FOR_EXECUTION"
            x.approved_by_user = True
            x.decision_note = f"[approved by user] {note}"[:200]
    rrepos.experiments.save(x)
    return x
