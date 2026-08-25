"""Customer analyzer: segments, evidence-derived personas, JTBD, pain engine,
workflow mapping.

Discipline:
- Personas are NEVER invented: <2 independent supporting evidences => the
  persona stays flagged `speculative` (spec #11).
- Pain is classified (14 categories) and its evidence form recorded via the
  pain hierarchy — reported pain < observed workaround < repeated behavior
  < existing spending < switching < actual payment (spec #13/#14).
- user != buyer is always tracked (spec #10).
"""
from __future__ import annotations

import re

from research_engine.specialists.startup.models import (
    CurrentAlternative, JobToBeDone, Persona)
from research_engine.specialists.startup.identity import norm_name
from research_engine.specialists.startup.policies import (
    PAIN_EVIDENCE_HIERARCHY, classify_pain, pain_evidence_class)
from research_engine.storage.repositories import Repositories

_SEGMENT_HINTS = [
    ("smb", re.compile(r"\b(smb|small (?:and medium|business)|small business\w*|mom[- ]?and[- ]?pop)\b", re.I)),
    ("enterprise", re.compile(r"\b(enterprise|large (?:companies|corporations|enterprises))\b", re.I)),
    ("mid_market", re.compile(r"\b(mid[- ]market|mid[- ]sized)\b", re.I)),
    ("startup", re.compile(r"\b(startups?|early[- ]stage companies)\b", re.I)),
    ("consumer", re.compile(r"\b(consumers?|individuals?|households|b2c)\b", re.I)),
    ("clinic_healthcare", re.compile(r"\b(clinics?|hospitals?|healthcare providers?)\b", re.I)),
    ("logistics_operators", re.compile(r"\b(fleet operators?|logistics compan\w+|carriers?)\b", re.I)),
    ("retailers", re.compile(r"\b(retailers?|stores?|e[- ]commerce sellers?)\b", re.I)),
]

_ROLE_RE = re.compile(
    r"\b(founder|ceo|cto|cfo|coo|ops manager|operations manager|store manager|"
    r"practice manager|procurement (?:manager|head)|it manager|marketing head|"
    r"fleet manager|owner|proprietor|admin head)\b", re.I)

_TOOL_RE = re.compile(
    r"\b(tally|excel|spreadsheets?|quickbooks|zoho|salesforce|hubspot|sap|"
    r"oracle|notion|slack|whatsapp(?: business)?|google sheets?|airtable)\b", re.I)


class CustomerAnalyzer:
    def __init__(self, repos: Repositories, provider=None, srepos=None):
        self.repos = repos
        self.provider = provider
        self.srepos = srepos

    def accepted(self, project_id: str) -> list:
        return [e for e in self.repos.evidence.all(project_id)
                if e.status != "REJECTED"]

    # ------------------------------------------------------------- segments
    def detect_segments(self, project_id: str) -> list[dict]:
        """Evidence-backed segment detection. Each segment carries its evidences."""
        segs: dict[str, dict] = {}
        for ev in self.accepted(project_id):
            text = ev.claim_text or ""
            for name, rx in _SEGMENT_HINTS:
                if not rx.search(text):
                    continue
                entry = segs.setdefault(name, {"name": name, "evidence_ids": [],
                                               "pain_claims": [], "buyer": "",
                                               "user": "", "budget_signals": []})
                entry["evidence_ids"].append(ev.id)
                if len(text) > 20 and len(entry["pain_claims"]) < 8:
                    entry["pain_claims"].append(text[:200])
                role = _ROLE_RE.search(text)
                if role and not entry["buyer"]:
                    entry["buyer"] = role.group(0).lower()
                spend = re.search(r"(?:spends?|paying|budget of)[^.]{0,60}", text, re.I)
                if spend and len(entry["budget_signals"]) < 3:
                    entry["budget_signals"].append(spend.group(0)[:100])
        return list(segs.values())

    # ------------------------------------------------------------- personas
    def build_personas(self, project_id: str, segments: list[dict]) -> list[Persona]:
        """Evidence-derived personas only; speculative flag stays until >=2
        independent evidences exist (spec #11)."""
        personas = []
        for seg in segments:
            eids = seg["evidence_ids"]
            tools = set()
            for eid in eids:
                ev = self.repos.evidence.get(eid)
                if ev:
                    for t in _TOOL_RE.findall((ev.claim_text or "") + " " + (ev.quote or "")):
                        tools.add(t.lower())
            p = Persona(
                project_id=project_id,
                role=seg.get("buyer") or f"{seg['name']} decision maker",
                organization_type=seg["name"],
                job_to_be_done=(seg["pain_claims"][0][:160] if seg["pain_claims"] else ""),
                existing_tools=sorted(tools)[:8],
                decision_authority=("buyer identified from evidence: "
                                    + seg["buyer"] if seg.get("buyer") else "UNKNOWN — user/buyer split unresolved"),
                budget_signal="; ".join(seg.get("budget_signals", []))[:200],
                segment_id=seg["name"],
                evidence_ids=eids[:12],
                speculative=len(eids) < 2,
            )
            p.confidence = round(min(0.9, 0.2 * min(len(eids), 4)), 2)
            p.ensure_id()
            personas.append(p)
            if self.srepos is not None:
                self.srepos.personas.save_natural(p)
        return personas

    # ------------------------------------------------------------- pains
    def analyze_pains(self, project_id: str) -> list[dict]:
        """Classify every pain-bearing evidence: category, hierarchy class,
        severity/frequency hints, current workaround.

        Returns dicts sorted by evidence strength (hierarchy weight), so the
        caller sees strongest behavioral evidence first.
        """
        rows = []
        for ev in self.accepted(project_id):
            claim = ev.claim_text or ""
            cats = classify_pain(claim)
            eclass = pain_evidence_class(claim)
            # Behavioral signals (spending/switching/workarounds) indicate pain
            # even when no pain-vocabulary word appears (spec #14).
            if cats == ["unclassified"] and eclass == "reported_pain":
                continue
            if cats == ["unclassified"]:
                cats = ["behavioral_signal"]
            workaround = ""
            m = re.search(r"(?:workaround|manually|instead)[^.]{0,120}", claim, re.I)
            if m:
                workaround = m.group(0)[:140]
            freq = bool(re.search(r"\b(daily|every day|every week|weekly|each week|"
                                  r"every month|often|repeatedly|always)\b",
                                  claim, re.I))
            sev_hint = 1.0 if eclass == "actual_payment" else \
                0.8 if eclass == "existing_spending" else \
                0.6 if eclass in ("repeated_behavior", "switching_behavior") else \
                0.45 if eclass == "observed_workaround" else 0.25
            rows.append({
                "evidence_id": ev.id, "statement": claim[:300],
                "categories": cats, "evidence_class": eclass,
                "hierarchy_weight": PAIN_EVIDENCE_HIERARCHY[eclass],
                "frequency_signal": freq, "severity_hint": sev_hint,
                "workaround": workaround,
                "source_tier": ev.source_tier,
            })
        rows.sort(key=lambda r: -r["hierarchy_weight"])
        return rows

    # ------------------------------------------------------------- alternatives
    def extract_alternatives(self, project_id: str) -> list[CurrentAlternative]:
        """Current alternatives incl. 'doing nothing' (spec #16)."""
        alts: dict[str, CurrentAlternative] = {}

        def add(name: str, kind: str, ev):
            a = alts.get(name)
            if a is None:
                a = CurrentAlternative(project_id=project_id, name=name, kind=kind)
                a.ensure_id()
                alts[name] = a
            if ev.id not in a.evidence_ids:
                a.evidence_ids.append(ev.id)

        for ev in self.accepted(project_id):
            t = ev.claim_text or ""
            low = t.lower()
            if _TOOL_RE.search(t):
                for tool in set(_TOOL_RE.findall(t)):
                    kind = "spreadsheet" if ("excel" in tool or "sheet" in tool) else "software"
                    add(tool.title(), kind, ev)
            if re.search(r"\b(manual\w*|by hand|paper[- ]based)\b", low):
                add("manual process", "manual_labor", ev)
            if re.search(r"\b(consultant\w*|agency|outsourc\w+)\b", low):
                add("consultant/outsourcing", "consultant", ev)
            if re.search(r"\b(intern\w*|assistant|back office|ops team)\b", low):
                add("internal employee", "internal_employee", ev)
            if re.search(r"\b(do nothing|live with it|ignore[d]? the problem|no solution)\b", low):
                add("do nothing", "do_nothing", ev)
        out = sorted(alts.values(), key=lambda a: -len(a.evidence_ids))
        if self.srepos is not None:
            for a in out:
                self.srepos.alternatives.save_natural(a)
        return out

    # ------------------------------------------------------------- workflow
    def map_workflow(self, project_id: str, topic: str) -> dict:
        """Reconstruct the current workflow around `topic` from evidence order
        (spec #15). Deterministic: steps are evidence claims mentioning the
        topic, ordered by iteration then id."""
        steps = []
        problems = {"time-consuming": [], "expensive": [], "error_prone": [],
                    "manual": [], "coordination": []}
        key_rx = re.compile(re.escape(topic.lower()[:24]), re.I) if topic else None
        for ev in sorted(self.accepted(project_id), key=lambda e: (e.iteration, e.id)):
            claim = ev.claim_text or ""
            if key_rx and not (key_rx.search(claim) or key_rx.search(ev.quote or "")):
                continue
            low = claim.lower()
            if re.search(r"\b(manual\w*|copy[- ]past\w*|re-?enter)\b", low):
                problems["manual"].append(claim[:120])
            if re.search(r"\b(hours?|days?|slow|time[- ]consuming)\b", low):
                problems["time-consuming"].append(claim[:120])
            if re.search(r"\b(cost\w*|expensive|\$|₹)\b", low):
                problems["expensive"].append(claim[:120])
            if re.search(r"\b(error\w*|mistakes?|wrong|inaccurat\w+)\b", low):
                problems["error_prone"].append(claim[:120])
            if re.search(r"\b(between teams|handoff|coordinat\w+)\b", low):
                problems["coordination"].append(claim[:120])
            if claim not in steps:
                steps.append(claim[:180])
        return {
            "topic": topic,
            "steps": steps[:10],
            "friction_points": {k: v[:3] for k, v in problems.items() if v},
        }

    # ------------------------------------------------------------- JTBD
    def build_jtbd(self, project_id: str, segments: list[dict],
                   pains: list[dict], alternatives: list[CurrentAlternative]
                   ) -> list[JobToBeDone]:
        jobs = []
        top_alt = alternatives[0].name if alternatives else "unknown"
        for seg in segments:
            # pains tied to this segment via shared evidence
            seg_ev = set(seg["evidence_ids"])
            seg_pains = [p for p in pains if p["evidence_id"] in seg_ev] or pains[:2]
            primary = seg_pains[0] if seg_pains else None
            j = JobToBeDone(
                project_id=project_id,
                segment_id=seg["name"],
                functional_job=(primary["statement"][:200] if primary
                                else f"{seg['name']} need to handle their core workflow reliably"),
                trigger=(primary["workaround"][:120] if primary and primary["workaround"]
                         else ""),
                desired_outcome="problem removed without adding workflow burden",
                current_alternative=top_alt,
                pain_ids=[p["evidence_id"] for p in seg_pains[:5]],
                friction="; ".join(p["categories"][0] for p in seg_pains[:3]),
                cost_of_failure=("; ".join(p["workaround"] for p in seg_pains
                                           if p["workaround"])[:150]),
                evidence_ids=list(seg_ev)[:10],
            )
            j.ensure_id()
            jobs.append(j)
            if self.srepos is not None:
                self.srepos.jtbd.save_natural(j)
        return jobs
