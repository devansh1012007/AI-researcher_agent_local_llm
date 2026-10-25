"""Tests for Phase 2B prompt correctness & structured LLM contracts (P1-2, P1-3, P1-8, P1-9)."""
from __future__ import annotations

from pathlib import Path

import pytest

from research_engine.core.config import LLMRoleConfig
from research_engine.intelligence.falsification import AssumptionEngine
from research_engine.models.opportunity import Opportunity
from research_engine.models.reasoning import Hypothesis
from research_engine.prompts import registry
from research_engine.prompts.registry import PromptSpec, get_prompt, record_versions
from research_engine.providers.llm.base import LLMError, LLMProvider
from research_engine.reasoning.methodology_designer import MethodologyDesigner
from research_engine.specialists.startup.assumptions import BusinessAssumptionBuilder
from research_engine.storage.database import Database
from research_engine.storage.reasoning_repos import ReasoningRepos
from research_engine.storage.repositories import Repositories


class _OutageProvider(LLMProvider):
    def __init__(self, msg: str = "connection refused; api_key=sk-secret99999999"):
        super().__init__(LLMRoleConfig(provider="ollama", model="qwen2.5:7b"))
        self.msg = msg

    def _raw_complete(self, system: str, user: str) -> str:
        raise LLMError(self.msg)


class _MalformedProvider(LLMProvider):
    def __init__(self):
        super().__init__(LLMRoleConfig(provider="mock", model="mock"))

    def _raw_complete(self, system: str, user: str) -> str:
        return "not json at all"


class _EmptyValidProvider(LLMProvider):
    def __init__(self):
        super().__init__(LLMRoleConfig(provider="mock", model="mock"))

    def _raw_complete(self, system: str, user: str) -> str:
        return '{"assumptions": [], "cheap_fast": {}, "balanced": {}, "high_rigor": {}, "cheapest_test": ""}'


class _ValidStructuredProvider(LLMProvider):
    def __init__(self):
        super().__init__(LLMRoleConfig(provider="mock", model="mock"))

    def _raw_complete(self, system: str, user: str) -> str:
        if "Design THREE methodologies" in user:
            return (
                '{"cheap_fast": {"experiment_kind": "experiment", "objective": "obj1", '
                '"method_summary": "fast method", "metrics": ["m1"]}, '
                '"balanced": {"experiment_kind": "ablation", "objective": "obj2", '
                '"method_summary": "balanced method", "metrics": ["m2"]}, '
                '"high_rigor": {"experiment_kind": "benchmark", "objective": "obj3", '
                '"method_summary": "rigorous method", "metrics": ["m3"]}}'
            )
        if "Design the cheapest decisive falsification test" in user:
            return (
                '{"assumption": "a1", "cheapest_test": "run 10 interviews", '
                '"success_condition": ">=5 confirm", "failure_condition": "<2 confirm", '
                '"decision_rule": "continue if >=5 else abandon"}'
            )
        return '{"assumptions": ["Custom assumption alpha", "Custom assumption beta"]}'


class TestP1_2_RoleSpecificTemplates:
    def test_role_specific_templates_exist_and_load(self):
        for name in ("assumption_generator", "methodology_designer", "falsification_designer"):
            spec = get_prompt(name)
            assert spec.version == "v1"
            assert spec.system.strip()
            assert spec.template.strip()
            assert "query_generator" not in spec.system

    def test_query_generator_never_used_by_non_query_generation_callers(self):
        src_root = Path(__file__).resolve().parents[2] / "src" / "research_engine"
        allowed = {"pipeline/planning.py", "reasoning/adaptive_planner.py"}
        offenders = []
        for py in src_root.rglob("*.py"):
            rel = str(py.relative_to(src_root)).replace("\\", "/")
            if rel in allowed:
                continue
            text = py.read_text()
            if '"query_generator"' in text or "'query_generator'" in text:
                offenders.append(rel)
        assert not offenders, f"Non-query-generation modules using query_generator: {offenders}"

    def test_consumers_render_their_dedicated_templates(self, tmp_path, monkeypatch):
        called_names: list[str] = []
        orig_get_prompt = registry.get_prompt

        def spy_get_prompt(name: str, version: str | None = None):
            called_names.append(name)
            return orig_get_prompt(name, version)

        monkeypatch.setattr("research_engine.specialists.startup.assumptions.get_prompt", spy_get_prompt)
        monkeypatch.setattr("research_engine.reasoning.methodology_designer.get_prompt", spy_get_prompt)
        monkeypatch.setattr("research_engine.intelligence.falsification.get_prompt", spy_get_prompt)

        db = Database(tmp_path / "t.sqlite")
        repos = Repositories(db)
        rrepos = ReasoningRepos(db)
        prov = _ValidStructuredProvider()

        hyp = Hypothesis(project_id="p", title="t", statement="Customers pay for X", type="CUSTOMER")
        hyp.ensure_id()
        rrepos.hypotheses.save(hyp)

        builder = BusinessAssumptionBuilder(rrepos, prov)
        asm = builder.build_for_hypothesis("p", "opp_1", hyp)
        assert asm and asm[0].statement == "Custom assumption alpha"

        designer = MethodologyDesigner(repos, rrepos, prov)
        meths = designer.design("p", hyp)
        assert len(meths) == 3
        assert meths[0].method_summary == "fast method"

        opp = Opportunity(
            project_id="p",
            problem="bookkeeping pain",
            customer_segment="SMBs",
            current_alternative="spreadsheets",
        )
        opp.ensure_id()
        repos.opportunities.save(opp)
        eng = AssumptionEngine(repos, prov)
        crit = eng.critical_assumptions(opp)
        assert crit == ["Custom assumption alpha", "Custom assumption beta"]
        opp.critical_assumptions = crit
        tests = eng.design_falsification_tests("p", opp, max_tests=1)
        assert len(tests) == 1
        assert tests[0].cheapest_test == "run 10 interviews"

        assert "assumption_generator" in called_names
        assert "methodology_designer" in called_names
        assert "falsification_designer" in called_names
        assert "query_generator" not in called_names


class TestP1_3_StructuredBoundaryFailureSemantics:
    def test_assumptions_distinguishes_outage_invalid_empty_unconfigured_and_ok(self, tmp_path):
        db = Database(tmp_path / "t.sqlite")
        rrepos = ReasoningRepos(db)
        hyp = Hypothesis(project_id="p", title="t", statement="S", type="CUSTOMER")
        hyp.ensure_id()

        # 1. Unconfigured
        b_none = BusinessAssumptionBuilder(rrepos, None)
        b_none.build_for_hypothesis("p", "opp_1", hyp)
        assert b_none.last_outcome["status"] == "unconfigured"
        assert b_none.last_outcome["fallback_used"] is True

        # 2. Provider outage (with secret in error text that must be redacted)
        b_fail = BusinessAssumptionBuilder(rrepos, _OutageProvider())
        b_fail.build_for_hypothesis("p", "opp_1", hyp)
        assert b_fail.last_outcome["status"] == "provider_failed"
        assert b_fail.last_outcome["provider"] == "ollama"
        assert b_fail.last_outcome["error_category"] != ""
        assert "sk-secret" not in b_fail.last_outcome["reason"]
        assert b_fail.last_outcome["fallback_used"] is True

        # 3. Invalid / malformed structured output
        b_bad = BusinessAssumptionBuilder(rrepos, _MalformedProvider())
        b_bad.build_for_hypothesis("p", "opp_1", hyp)
        assert b_bad.last_outcome["status"] == "invalid_output"
        assert b_bad.last_outcome["error_category"] == "VALIDATION"
        assert b_bad.last_outcome["fallback_used"] is True

        # 4. Valid empty output
        b_empty = BusinessAssumptionBuilder(rrepos, _EmptyValidProvider())
        b_empty.build_for_hypothesis("p", "opp_1", hyp)
        assert b_empty.last_outcome["status"] == "empty_output"
        assert b_empty.last_outcome["fallback_used"] is True

        # 5. Valid non-empty output
        b_ok = BusinessAssumptionBuilder(rrepos, _ValidStructuredProvider())
        b_ok.build_for_hypothesis("p", "opp_1", hyp)
        assert b_ok.last_outcome["status"] == "ok"
        assert b_ok.last_outcome["fallback_used"] is False

    def test_methodology_and_falsification_record_provider_outage_distinctly(self, tmp_path):
        db = Database(tmp_path / "t.sqlite")
        repos = Repositories(db)
        rrepos = ReasoningRepos(db)
        hyp = Hypothesis(project_id="p", title="t", statement="S", type="MECHANISTIC")
        hyp.ensure_id()

        md_fail = MethodologyDesigner(repos, rrepos, _OutageProvider())
        md_fail.design("p", hyp)
        assert md_fail.last_outcome["status"] == "provider_failed"
        assert "sk-secret" not in md_fail.last_outcome["reason"]

        md_empty = MethodologyDesigner(repos, rrepos, _EmptyValidProvider())
        md_empty.design("p", hyp)
        assert md_empty.last_outcome["status"] == "empty_output"

        opp = Opportunity(project_id="p", problem="p", customer_segment="s", current_alternative="a")
        opp.ensure_id()
        opp.critical_assumptions = ["a1"]
        repos.opportunities.save(opp)

        fe_fail = AssumptionEngine(repos, _OutageProvider())
        fe_fail.critical_assumptions(opp)
        assert fe_fail.last_outcome["status"] == "provider_failed"
        fe_fail.design_falsification_tests("p", opp, max_tests=1)
        assert fe_fail.last_outcome["status"] == "provider_failed"

        fe_empty = AssumptionEngine(repos, _EmptyValidProvider())
        fe_empty.critical_assumptions(opp)
        assert fe_empty.last_outcome["status"] == "empty_output"


class TestP1_8_UntrustedBracesInPromptRender:
    def test_untrusted_value_with_double_braces_renders_verbatim(self):
        spec = get_prompt("query_generator")
        rendered = spec.render(
            branch_question="What is X?",
            required_evidence=" empirical data ",
            context="Scraped text containing {{unknown_var}} and {{ another_brace }}",
            n_queries=3,
        )
        assert "{{unknown_var}}" in rendered
        assert "{{ another_brace }}" in rendered

    def test_missing_template_placeholder_still_raises_value_error(self):
        spec = get_prompt("query_generator")
        with pytest.raises(ValueError, match="unknown/unfilled placeholder 'context'"):
            spec.render(
                branch_question="What is X?",
                required_evidence="data",
                n_queries=3,
            )

    def test_template_with_whitespace_inside_braces_substitutes_and_validates(self):
        spec = PromptSpec(
            name="custom_ws",
            version="v1",
            system="sys",
            template="Hello {{ user_name }}! Body: {{ body_text }}",
        )
        with pytest.raises(ValueError, match="body_text"):
            spec.render(user_name="Alice")
        out = spec.render(user_name="Alice", body_text="literal {{unfilled_in_val}}")
        assert out == "Hello Alice! Body: literal {{unfilled_in_val}}"


class TestP1_9_NumericPromptVersionSelection:
    def test_latest_version_selects_v10_over_v2_and_normalizes_version(self, tmp_path, monkeypatch):
        tdir = tmp_path / "templates"
        pdir = tdir / "sample_prompt"
        pdir.mkdir(parents=True)
        for ver in ("v1", "v2", "v10"):
            (pdir / f"{ver}.txt").write_text(f"template for {ver}: {{{{item}}}}")
            (pdir / f"{ver}.meta.yaml").write_text(f"system: system for {ver}\n")
        # Also create a malformed version filename that must be ignored
        (pdir / "vbeta.txt").write_text("malformed")

        monkeypatch.setattr(registry, "TEMPLATES_DIR", tdir)
        registry._load.cache_clear()
        try:
            latest = get_prompt("sample_prompt")
            assert latest.version == "v10"
            assert "template for v10" in latest.template
            assert latest.system.strip() == "system for v10"

            v2 = get_prompt("sample_prompt", version="2")
            assert v2.version == "v2"
            v2_prefixed = get_prompt("sample_prompt", version="v2")
            assert v2_prefixed.version == "v2"

            recorded = record_versions()
            assert recorded["sample_prompt"] == "v10"
            assert recorded["sample_prompt"] == latest.version
        finally:
            registry._load.cache_clear()
