"""Research watchers: living research via incremental updates (spec #17-20).

A watcher monitors a query against configured providers on a schedule.
Each tick:
  1. search providers for the watch query
  2. compare against known sources (url -> content hash)
  3. new URLs / changed content -> SOURCE_UPDATED events
  4. fetch + extract ONLY new/changed documents (incremental, spec #19)
  5. flag affected claims/hypotheses; publish notification events (#21)

Watchers never rerun full research and never loop infinitely: a tick that
finds nothing increments consecutive_empty_runs; after N empty ticks the
watcher backs off (frequency doubles, capped) instead of hammering.
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any

from research_engine.models.job import Watcher as WatcherModel
from research_engine.platform.events import DomainEvent, EventBus


class SourceChangeDetector:
    """same URL + different content => SOURCE_UPDATED (spec #20)."""

    def __init__(self, db):
        # db: project Database (source_versions table exists from Phase 2)
        self.db = db

    def diff(self, project_id: str,
             hits: list[dict]) -> dict[str, list[dict]]:
        """Classify hits into new/changed/unchanged by content hash."""
        out: dict[str, list[dict]] = {"new": [], "changed": [], "unchanged": []}
        for h in hits:
            url = h.get("url", "")
            body = h.get("body") or h.get("snippet") or ""
            digest = hashlib.sha256(body.encode("utf-8", "ignore")).hexdigest()[:16]
            prev = self._known_hash(project_id, url)
            entry = {**h, "content_hash": digest}
            if prev is None:
                out["new"].append(entry)
            elif prev != digest:
                out["changed"].append(entry)
            else:
                out["unchanged"].append(entry)
            self._remember(project_id, url, digest)
        return out

    def _known_hash(self, project_id: str, url: str) -> str | None:
        try:
            rows = self.db.execute(
                "SELECT data FROM source_versions WHERE project_id=? AND "
                "json_extract(data,'$.url')=? ORDER BY observed_at DESC LIMIT 1",
                (project_id, url))
        except Exception:
            return None
        for r in rows:
            return json_loads(r["data"]).get("new_hash") or \
                json_loads(r["data"]).get("content_hash")
        return None

    def _remember(self, project_id: str, url: str, digest: str) -> None:
        import json as _json
        now = datetime.now(timezone.utc).isoformat()
        vid = f"sv_{now}_{hashlib.md5(url.encode()).hexdigest()[:8]}"
        payload = {"id": vid, "project_id": project_id, "url": url,
                   "content_hash": digest, "source_id": "",
                   "observed_at": now}
        try:
            with self.db._conn() as c:
                c.execute(
                    """INSERT OR REPLACE INTO source_versions
                       (id, project_id, source_id, observed_at, data)
                       VALUES(?,?,?,?,?)""",
                    (vid, project_id, "", now, _json.dumps(payload)))
        except Exception:
            pass


def json_loads(s: str) -> dict:
    import json
    return json.loads(s)


class WatchRunner:
    """Executes one watcher tick. Registered as WATCHER_TICK runner."""

    def __init__(self, ctx, bus: EventBus | None = None):
        self.ctx = ctx
        self.bus = bus or EventBus()

    def tick(self, watcher: WatcherModel, control_fn=None) -> dict:
        if control_fn and control_fn(watcher.project_id) == "CANCEL":
            return {"status": "CANCELLED"}
        from research_engine.core.orchestrator import Orchestrator
        orch = Orchestrator.load(self.ctx.cfg, watcher.project_id)

        hits = self._search(watcher.query, watcher.source_scope)
        detector = SourceChangeDetector(orch.db)
        diff = detector.diff(watcher.project_id, hits)

        extracted = 0
        new_evidence_ids: list[str] = []
        interesting = diff["new"] + diff["changed"]
        if interesting and watcher.action == "incremental_update":
            ev_before = {e.id for e in orch.repos.evidence.all(orch.project.id)}
            extracted = self._extract_incremental(orch, interesting)
            if extracted:
                new_evidence_ids = [e.id for e in
                                    orch.repos.evidence.all(orch.project.id)
                                    if e.id not in ev_before]

        # notifications (spec #21/#133). New sources and changed sources are
        # DIFFERENT events; the old code published EvidenceCreated for both
        # via a dead `if False` conditional.
        for item in diff["new"]:
            self.bus.publish(DomainEvent(
                "EvidenceCreated",
                project_id=watcher.project_id,
                payload={"kind": "new_source", "url": item["url"],
                         "title": item.get("title", "")[:120]}))
        for item in diff["changed"]:
            self.bus.publish(DomainEvent(
                "SourceUpdated", project_id=watcher.project_id,
                payload={"kind": "SOURCE_UPDATED", "url": item["url"],
                         "affected": self._affected_summaries(orch, item)}))

        # backoff on persistent emptiness (no infinite loops, spec #165)
        w = watcher
        w.last_run_at = datetime.now(timezone.utc)
        if not interesting:
            w.consecutive_empty_runs += 1
        else:
            w.consecutive_empty_runs = 0
            w.last_change_at = w.last_run_at
        self.ctx.platform_db.save_watcher(w)
        summary = {"status": "OK", "new": len(diff["new"]),
                   "changed": len(diff["changed"]), "unchanged":
                   len(diff["unchanged"]), "extracted_evidence": extracted,
                   "empty_streak": w.consecutive_empty_runs}
        # ---- Phase 6 §80-§83: watcher → impact analysis → ranked alerts.
        # Targeted re-research is submitted only when the new evidence is
        # CONNECTED to claims/hypotheses/opportunities (impact traversal),
        # keeping noise bounded. Failures here never break the tick.
        if new_evidence_ids:
            try:
                from research_engine.adaptive.impact import (
                    analyze_new_evidence, raise_impact_alerts)
                raise_impact_alerts(self.ctx.platform_db, orch,
                                    w.project_id, new_evidence_ids,
                                    source=f"watcher:{w.id}")
                summary["alerts"] = True
            except Exception:
                pass
        if interesting or extracted:
            self.bus.publish(DomainEvent(
                "WatcherTriggered", project_id=w.project_id,
                payload={"watcher_id": w.id, **summary}))
        return summary

    # -------------------------------------------------------------- pieces
    def _search(self, query: str, scope: list[str]) -> list[dict]:
        """Query academic+web providers per scope; degrade gracefully."""
        from research_engine.core.orchestrator import build_default_registry
        reg = build_default_registry(self.ctx.cfg)
        hits: list[dict] = []
        wanted_academic = [s for s in scope if s != "web"] or \
            self.ctx.cfg.search.academic_providers
        want_web = not scope or "web" in scope
        timeout = self.ctx.cfg.network.timeout_seconds
        if want_web:
            try:
                from research_engine.providers.search.duckduckgo import \
                    DuckDuckGoProvider
                for r in DuckDuckGoProvider(timeout=timeout).search(query)[:5]:
                    hits.append({"url": r.url, "title": r.title,
                                 "snippet": r.snippet})
            except Exception:
                pass
        for name in wanted_academic[:3]:
            try:
                prov = reg.academic.get(name)
                if prov is None:
                    continue
                for r in prov.search(query, max_results=5):
                    hits.append({"url": r.url, "title": r.title,
                                 "snippet": r.snippet})
            except Exception:
                continue   # provider failure never kills the watcher
        seen: set[str] = set()
        uniq = []
        for h in hits:
            if h["url"] not in seen:
                seen.add(h["url"])
                uniq.append(h)
        return uniq

    def _extract_incremental(self, orch, items: list[dict]) -> int:
        """Fetch only new/changed docs; extract evidence into the graph."""
        from research_engine.models.enums import ContentStatus, SourceType
        from research_engine.models.research import Source
        sources = []
        for it in items[:10]:
            url = it["url"]
            src = Source(
                project_id=orch.project.id, url=url, canonical_url=url,
                title=(it.get("title") or "")[:300],
                domain=url.split("/")[0] if "/" in url else url,
                source_type=SourceType.RESEARCH_PAPER
                if "arxiv.org" in url else SourceType.OTHER,
                source_tier=1 if "arxiv.org" in url else 5,
                retrieval_date=datetime.now(timezone.utc).isoformat(),
                content_status=ContentStatus.DISCOVERED.value)
            src.ensure_id()
            sources.append(src)
            orch.repos.sources.save(src)
        problems = orch.repos.problems.all(orch.project.id)
        if problems:
            problem = problems[0]
            questions = "\n".join([problem.research_question] +
                                  problem.subquestions[:6])
        else:
            questions = orch.project.question_raw  # graceful: never crash tick
        try:
            from research_engine.pipeline.evidence import EvidenceWorker
            proc = orch._make_document_processor()
            docs = proc.process_sources(
                orch.project.id, sources,
                max_docs=self.cfg_max_docs())
            ev_worker = EvidenceWorker(self.ctx.cfg, orch.router.extractor,
                                       orch.repos)
            new_ev, _rej = ev_worker.extract_from_documents(
                orch.project.id, docs, questions,
                iteration=orch.project.current_iteration)
            return len(new_ev)
        except Exception:
            return 0

    def cfg_max_docs(self) -> int:
        return 10

    def _affected_summaries(self, orch, item: dict) -> list[str]:
        """Claims/hypotheses potentially affected by a changed source (#132)."""
        text = (item.get("title", "") + " " + item.get("snippet", ""))[:300]
        affected = []
        for c in orch.repos.claims.all(orch.project.id)[:400]:
            overlap = sum(1 for tok in set(text.lower().split()) & set(
                (c.text or "").lower().split()) if len(tok) > 4)
            if overlap >= 2:
                affected.append(c.id)
                break
        return affected[:3]
