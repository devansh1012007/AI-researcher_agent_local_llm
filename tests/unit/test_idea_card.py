"""Idea card parsing, verdict policy, founder fields (pure functions, no I/O)."""
from __future__ import annotations

import pytest

from research_engine.specialists.startup.idea import (
    CARD_KEYS, ESSENTIAL_KEYS, IdeaCard, answers_from_questions, build_idea_question,
    founder_fields, idea_verdict, merge_answers, parse_idea_card, parse_test_note)


def test_round_trip_build_then_parse():
    q = build_idea_question("AI tutor for JEE", problem="students cannot get doubts solved at night",
                            customer_segment="JEE aspirants in Kota", price_point="Rs 299 per month")
    c = parse_idea_card(q)
    assert c.idea == "AI tutor for JEE"
    assert c.problem.startswith("students cannot")
    assert c.customer_segment == "JEE aspirants in Kota"
    assert c.missing_essential() == []
    assert set(c.missing_optional()) >= {"geography", "existing_traction"}


def test_plain_sentence_is_the_idea_and_essentials_are_missing():
    c = parse_idea_card("Evaluate startup idea: dog walking marketplace")
    assert c.idea == "dog walking marketplace"
    assert c.missing_essential() == list(ESSENTIAL_KEYS)


def test_aliases_and_continuation_lines():
    c = parse_idea_card("Idea one\nCustomer: freelance designers\n  who bill hourly\nPricing = $20/mo")
    assert c.customer_segment == "freelance designers who bill hourly"
    assert c.price_point == "$20/mo"


def test_unknown_labels_are_not_swallowed_as_fields():
    c = parse_idea_card("Idea one\nNote: this is not a field\nproblem: p")
    assert c.problem == "p"
    assert "note" not in c.to_dict()


def test_empty_and_garbage_input_never_raises():
    assert parse_idea_card("").idea == ""
    assert parse_idea_card(None).idea == ""
    assert parse_idea_card(":::\n===").idea != "x"


def test_build_rejects_unknown_field_and_empty_idea():
    with pytest.raises(ValueError):
        build_idea_question("x", colour="blue")
    with pytest.raises(ValueError):
        build_idea_question("  ")


def test_required_inputs_in_pack_match_card_keys():
    """The pack's required_inputs ARE the card labels; drift would re-ask answered fields."""
    from research_engine.engines.loader import get_engine
    assert list(get_engine("startup_validation").clarifier.required_inputs) == [
        "customer_segment", "problem", "alternative", "price_point",
        "riskiest_assumption", "geography", "existing_traction", "founder_constraints"]
    assert set(get_engine("startup_validation").clarifier.required_inputs) == set(CARD_KEYS)


class _Q:
    def __init__(self, text, status, answer):
        self.text, self.status, self.answer = text, status, answer


def test_answers_override_card_and_only_answered_count():
    qs = [_Q("Please specify geography for this research project.", "ANSWERED", " India "),
          _Q("Please specify price_point for this research project.", "OPEN", ""),
          _Q("Something unrelated", "ANSWERED", "x")]
    answers = answers_from_questions(qs)
    assert answers == {"geography": "India"}
    c = merge_answers(parse_idea_card("idea\ngeography: Nepal"), answers)
    assert c.geography == "India" and c.sources["geography"] == "answer"


GATE_OK = {"speculative": False, "missing": [],
           "checks": {"counterevidence_searched": True, "competition_researched": True}}


def _card():
    return IdeaCard(idea="i", problem="p", customer_segment="c")


def test_positive_verdict_requires_counterevidence_and_competition():
    rec = {"decision": "start_validating"}
    assert idea_verdict(_card(), gate=GATE_OK, recommendation=rec,
                        falsified_critical=0, linked_evidence=3)["verdict"] == "VALIDATE_NEXT"
    for missing in ("counterevidence_searched", "competition_researched"):
        gate = {**GATE_OK, "checks": {**GATE_OK["checks"], missing: False}}
        v = idea_verdict(_card(), gate=gate, recommendation=rec,
                         falsified_critical=0, linked_evidence=3)
        assert v["verdict"] == "RESEARCH_MORE" and not v["positive"]
        assert missing in " ".join(v["reasons"])


def test_guard_order_falsified_beats_everything_and_undefined_beats_evidence():
    rec = {"decision": "start_validating"}
    assert idea_verdict(_card(), gate=GATE_OK, recommendation=rec, falsified_critical=1,
                        linked_evidence=9)["verdict"] == "STOP_OR_PIVOT"
    assert idea_verdict(IdeaCard(idea="i"), gate=GATE_OK, recommendation=rec, falsified_critical=0,
                        linked_evidence=9)["verdict"] == "DEFINE_THE_IDEA"
    assert idea_verdict(_card(), gate={**GATE_OK, "speculative": True}, recommendation=rec,
                        falsified_critical=0, linked_evidence=0)["verdict"] == "NOT_ENOUGH_EVIDENCE"


def test_founder_fields_structured_only_never_guessed():
    f = founder_fields("skills=python, ml; capital=bootstrap; time=10 hours per week")
    assert f == {"skills": ["python", "ml"], "capital": "bootstrap", "time_available": "10 hours per week"}
    assert founder_fields("I am a solo founder with some savings") == {}


def test_parse_test_note():
    n = parse_test_note("type=interview; participants=15; success=>=50% recall; fail=<20% recall; "
                        "cost=low; decision=continue; opp=o1; info_gain=1.2")
    assert n["success"] == ">=50% recall" and n["fail"] == "<20% recall" and n["info_gain"] == "1.2"


def test_validate_idea_script_builds_the_same_card(capsys):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "scripts" / "validate_idea.py"
    spec = importlib.util.spec_from_file_location("validate_idea", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["Idea X", "--problem", "p", "--customer-segment", "c", "--print-only"]) == 0
    out = capsys.readouterr().out
    c = parse_idea_card(out)
    assert (c.idea, c.problem, c.customer_segment) == ("Idea X", "p", "c")
    assert mod.main(["   ", "--print-only"]) == 2
