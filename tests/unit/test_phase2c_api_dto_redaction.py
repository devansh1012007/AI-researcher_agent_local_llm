"""Phase 2C tests: API error schema (P1-4), Project DTO (P1-5), and log/event redaction (P1-6)."""
from __future__ import annotations

import json
import time
import pytest


def test_api_error_responses_follow_canonical_schema(platform_ctx):
    from fastapi.testclient import TestClient
    from research_engine.api.app import create_app

    with TestClient(create_app(platform_ctx)) as client:
        # 404 NotFoundError
        r404 = client.get("/projects/proj_missing_123")
        assert r404.status_code == 404
        b404 = r404.json()
        assert set(b404.keys()) == {"error"}
        assert b404["error"]["code"] == "NOT_FOUND"
        assert "proj_missing_123" in b404["error"]["message"]
        assert "trace_id" in b404["error"]

        # 422 RequestValidationError
        r422 = client.post("/projects", json={"question": "short"})
        assert r422.status_code == 422
        b422 = r422.json()
        assert set(b422.keys()) == {"error"}
        assert b422["error"]["code"] == "VALIDATION_ERROR"
        assert "trace_id" in b422["error"]

        # 409 ConflictError (illegal review transition / value error)
        pid = client.post("/projects", json={"question": "Does RAG improve factual accuracy?"}).json()["id"]
        r409 = client.post(
            f"/projects/{pid}/review/decisions",
            json={"target_kind": "claim", "target_id": "clm_x", "verdict": "INVALID_VERDICT"},
        )
        assert r409.status_code == 409
        b409 = r409.json()
        assert set(b409.keys()) == {"error"}
        assert b409["error"]["code"] == "CONFLICT"


def test_api_401_unauthorized_uses_flat_error_envelope(platform_ctx):
    from fastapi.testclient import TestClient
    from research_engine.api.app import create_app

    platform_ctx.cfg.platform.api.host = "0.0.0.0"
    platform_ctx.cfg.platform.api.auth_token = "super_secret_token_val"
    try:
        with TestClient(create_app(platform_ctx)) as client:
            r401 = client.get("/projects")
            assert r401.status_code == 401
            b401 = r401.json()
            assert set(b401.keys()) == {"error"}
            assert b401["error"]["code"] == "UNAUTHORIZED"
            assert "detail" not in b401
    finally:
        platform_ctx.cfg.platform.api.host = "127.0.0.1"


def test_project_list_dto_exposes_question_created_at_and_sorts_newest_first(platform_ctx):
    from research_engine.services.research_service import ProjectCreate, ProjectService

    svc = ProjectService(platform_ctx)
    p1 = svc.create(ProjectCreate(question="First research question for sorting test", mode="academic"))
    time.sleep(0.01)
    p2 = svc.create(ProjectCreate(question="Second research question for sorting test", mode="startup"))

    listed = svc.list_projects()
    ids = [p["id"] for p in listed]
    assert ids.index(p2["id"]) < ids.index(p1["id"]), f"Expected newest first, got {ids}"
    for item in listed:
        assert "question" in item and item["question"]
        assert "question_raw" in item and item["question_raw"] == item["question"]
        assert "created_at" in item and item["created_at"]
        assert "updated_at" in item and item["updated_at"]


def test_event_log_and_research_log_redact_secrets(tmp_path):
    from research_engine.storage.events import EventLog

    ev = EventLog(tmp_path, redact_secrets=True)
    secret_str = "Failed with api_key=sk-1234567890abcdef and Authorization: Bearer tok_secret_999"
    ev.record(
        project_id="proj_1",
        event="provider_error",
        component="retrieval",
        status="error",
        metadata={"nested": {"token": "tok_secret_999", "detail": secret_str}},
        error=secret_str,
        human_line=f"- Error: {secret_str}",
    )
    jsonl_content = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    md_content = (tmp_path / "reports" / "research_log.md").read_text(encoding="utf-8")
    assert "sk-1234567890abcdef" not in jsonl_content
    assert "tok_secret_999" not in jsonl_content
    assert "sk-1234567890abcdef" not in md_content
    assert "tok_secret_999" not in md_content
    assert "<redacted>" in jsonl_content
    assert "<redacted>" in md_content
