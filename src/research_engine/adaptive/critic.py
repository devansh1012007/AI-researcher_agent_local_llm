"""Independent research critic (Phase 6 §42-§46).

Produces review FINDINGS about a completed run. It never modifies the
research (INV-004 preserved — reviews are separate rows). Independence
requirements honored structurally: deterministic checks run with no LLM at
all; the optional LLM pass uses a dedicated critic prompt and the REASONING
role model (never the synthesis model that produced the report).
"""
from __future__ import annotations

import random
import re
from datetime import datetime, timezone

RIGOR_LEVELS = ("STANDARD", "DEEP", "HIGH_RIGOR")


def rigor_profile(level: str) -> dict:
    """§45/§46: higher rigor adds verification passes, not just documents."""
    level = level if level in RIGOR_LEVELS else "STANDARD"
    return {
        "citation_audit": True,                    # all levels
        "quote_spot_check": level != "STANDARD",
        "counterevidence_recheck": level == "HIGH_RIGOR",
        "numerical_audit": level == "HIGH_RIGOR",
        "llm_critic_pass": level == "HIGH_RIGOR",
        "quote_sample_size": {"STANDARD": 0, "DEEP": 10, "HIGH_RIGOR": 25}[level],
    }


_MONEY = re.compile(r"\$\s?\d[\d,\.]*\s*[KMB]?\b", re.I)


def critique_run(orch, pid: str, run_id: str = "",
                 level: str = "STANDARD", llm=None) -> dict:
    """Deterministic-first review of a completed run. When `level` is
    HIGH_RIGOR and an `llm` (reasoning-role provider) is supplied, adds an
    independent LLM critique pass using the dedicated critic prompt (§43).
    Returns a review dict ready for platform_db.save_review."""
    profile = rigor_profile(level)
    findings: list[dict] = []

    def add(kind: str, severity: str, target_id: str, note: str):
        findings.append({"kind": kind, "severity": severity,
                         "target_id": target_id, "note": note[:300]})

    # -- citation audit ----------------------------------------------------
    claims = orch.repos.claims.all(pid)
    ev_all = {e.id: e for e in orch.repos.evidence.all(pid)}
    dangling = [c for c in claims
                if any(eid not in ev_all for eid in c.supported_by)]
    if dangling:
        add("missing_cited_evidence", "high",
            ",".join(c.id for c in dangling[:5]),
            f"{len(dangling)} claims cite evidence ids that do not exist")

    # unsupported FACT-kind claims are epistemic violations
    unsupported_facts = [c for c in claims
                         if not c.supported_by
                         and str(getattr(c.kind, "value", c.kind)) == "FACT"]
    if unsupported_facts:
        add("unsupported_fact_claim", "high",
            ",".join(c.id for c in unsupported_facts[:5]),
            f"{len(unsupported_facts)} FACT claims have no supporting evidence")

    # -- quote spot check (re-verify stored quotes against chunk text) -----
    if profile["quote_spot_check"] and ev_all:
        sample = list(ev_all.values())
        rng = random.Random(pid)
        rng.shuffle(sample)
        from research_engine.pipeline.evidence import verify_quote
        checked = 0
        for e in sample[:profile["quote_sample_size"]]:
            quote = getattr(e, "quote", "") or ""
            chunk_id = getattr(e, "chunk_id", "") or ""
            if not quote or not chunk_id:
                continue
            chunk = orch.repos.chunks.get(chunk_id)
            if chunk is None or not getattr(chunk, "text", ""):
                continue
            checked += 1
            if not verify_quote(chunk.text, quote):
                add("quote_verification_failed", "critical", e.id,
                    f"stored quote not found in source chunk: "
                    f"{quote[:80]!r}")

    # -- counterevidence recheck -------------------------------------------
    if profile["counterevidence_recheck"]:
        claims_wo_counter = [
            c for c in claims
            if c.supported_by and not c.contradicted_by
            and len(c.supported_by) >= 3]
        if claims_wo_counter:
            add("counterevidence_unprobed", "medium",
                ",".join(c.id for c in claims_wo_counter[:5]),
                f"{len(claims_wo_counter)} well-supported claims never faced "
                "a recorded counterevidence probe")

    # -- numerical audit (money magnitudes landmine class) ------------------
    if profile["numerical_audit"]:
        bad_money = []
        for e in ev_all.values():
            for n in (e.numbers or []):
                raw = getattr(n, "raw", "") or ""
                val = getattr(n, "value", None)
                if _MONEY.search(raw) and isinstance(val, (int, float)) \
                        and abs(val) >= 1e12:
                    bad_money.append(e.id)
        if bad_money:
            add("suspicious_magnitude", "high",
                ",".join(sorted(set(bad_money))[:5]),
                f"{len(set(bad_money))} evidence rows carry >= $1T magnitudes; "
                "possible magnitude-parse error")

    # -- independent LLM critique (HIGH_RIGOR only) --------------------------
    backend = "deterministic"
    if profile["llm_critic_pass"] and llm is not None:
        from pydantic import BaseModel
        from research_engine.models.evidence import ClaimKind

        class _Finding(BaseModel):
            kind: str = ""
            severity: str = ""
            target_id: str = ""
            note: str = ""

        class _CriticOut(BaseModel):
            findings: list[_Finding] = []

        excerpt_claims = "\n".join(
            f"{c.id} [{getattr(c.kind, 'value', c.kind)}] "
            f"{(getattr(c, 'text', '') or getattr(c, 'claim_text', ''))[:200]}"
            for c in claims[:25])
        excerpt_ev = "\n".join(
            f"{e.id} tier{e.source_tier} "
            f"{(getattr(e, 'source_title', '') or '')[:80]}: "
            f"{(e.claim_text or '')[:160]}"
            for e in list(ev_all.values())[:25])
        try:
            out, errs = llm.structured(
                _critic_system_prompt(),
                f"claims:\n{excerpt_claims or '(none)'}\n\n"
                f"evidence:\n{excerpt_ev or '(none)'}",
                _CriticOut)
            if out is not None:
                valid_ids = set(ev_all) | {c.id for c in claims}
                kept = [f for f in out.findings
                        if f.target_id in valid_ids][:10]
                dropped = len(out.findings) - len(kept)
                for f in kept:
                    add(f"llm_{f.kind or 'observation'}",
                        f.severity if f.severity in ("low", "medium", "high")
                        else "low", f.target_id, f"[llm-critic] {f.note}")
                if dropped:
                    add("llm_findings_dropped", "info", "",
                        f"{dropped} LLM findings cited unknown ids; dropped")
                backend = "llm_reasoning_role"
        except Exception:
            add("llm_critic_error", "info", "",
                "LLM critic pass failed; deterministic findings retained")

    # -- bias risk proxy: source concentration ------------------------------
    domains = {}
    for e in ev_all.values():
        d = (e.source_url or "").split("/")[0] if e.source_url else ""
        domains[d] = domains.get(d, 0) + 1
    total = sum(domains.values()) or 1
    top_domain, top_n = max(domains.items(), key=lambda kv: kv[1]) \
        if domains else ("", 0)
    bias_risk = round(top_n / total, 3) if top_domain else 0.0

    dimensions = {
        "findings_count": len(findings),
        "critical": sum(1 for f in findings if f["severity"] == "critical"),
        "high": sum(1 for f in findings if f["severity"] == "high"),
        "bias_risk_top_source_share": bias_risk,
        "rigor_level": level,
    }
    return {
        "review_id": f"rev_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
                     f"_{abs(hash((pid, run_id))) % 99999}",
        "project_id": pid,
        "run_id": run_id,
        "dimensions": dimensions,
        "findings": findings,
        "critic_backend": backend,
        "prompt_version": "v1" if backend == "llm_reasoning_role" else "",
    }


def _critic_system_prompt() -> str:
    from research_engine.prompts.registry import get_prompt
    return get_prompt("critic_review").system
