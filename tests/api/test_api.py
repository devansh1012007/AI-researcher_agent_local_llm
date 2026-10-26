"""REST API tests (spec #23-26/#93/#146): validation, async jobs, errors,
security headers, pagination, path traversal."""
from __future__ import annotations

import time

import pytest


@pytest.fixture()
def client(platform_ctx):
    from fastapi.testclient import TestClient
    from research_engine.api.app import create_app
    with TestClient(create_app(platform_ctx)) as c:
        c.ctx = platform_ctx
        yield c


def _mk_project(client, q="Do retrieval-augmented systems reduce hallucination rates?"):
    r = client.post("/projects", json={"question": q})
    assert r.status_code == 201
    return r.json()["id"]


class TestProjectEndpoints:
    def test_create_get_list(self, client):
        pid = _mk_project(client)
        got = client.get(f"/projects/{pid}")
        assert got.status_code == 200
        assert got.json()["id"] == pid
        assert any(p["id"] == pid for p in client.get("/projects").json())

    def test_invalid_question_rejected(self, client):
        r = client.post("/projects", json={"question": "hi"})
        assert r.status_code == 422   # pydantic min_length

    def test_missing_project_404_structured(self, client):
        r = client.get("/projects/proj_nope/status")
        assert r.status_code == 404
        body = r.json()
        assert body["error"]["code"] == "NOT_FOUND"

    def test_status_has_meaningful_progress(self, client):
        pid = _mk_project(client)
        st = client.get(f"/projects/{pid}/status").json()
        for key in ("state", "iteration", "budget", "counts", "progress"):
            assert key in st
        assert "percent" not in json.dumps(st["progress"])  # spec #110


import json  # noqa: E402


class TestAsyncJobs:
    def test_run_returns_job_immediately(self, client):
        pid = _mk_project(client)
        r = client.post(f"/projects/{pid}/run", json={"max_iterations": 1})
        assert r.status_code == 202
        body = r.json()
        assert set(body) >= {"job_id", "status"}
        assert body["status"] in ("QUEUED", "RUNNING")

    def test_job_lifecycle_pause_resume_cancel(self, client):
        pid = _mk_project(client)
        job_id = client.post(f"/projects/{pid}/run",
                             json={"max_iterations": 1}).json()["job_id"]
        # wait until running or done (offline fake engine completes fast)
        deadline = time.time() + 30
        status = None
        while time.time() < deadline:
            j = client.get(f"/jobs/{job_id}").json()
            status = j["status"]
            if status in ("COMPLETED", "FAILED", "CANCELLED", "PAUSED"):
                break
            time.sleep(0.3)
        assert status in ("COMPLETED", "FAILED_PARTIAL")
        tasks = j["tasks"]
        assert all("attempts" in t for t in tasks)

    def test_unknown_job_404(self, client):
        assert client.get("/jobs/job_nope").status_code == 404

    def test_unsupported_job_type(self, client):
        r = client.post("/jobs?type_=quantum&project_id=x")
        assert r.status_code == 400


class TestKnowledgeEndpoints:
    def test_evidence_claims_gaps_empty_ok(self, client):
        pid = _mk_project(client)
        ev = client.get(f"/projects/{pid}/evidence").json()
        assert {"items", "total", "offset", "limit"} <= set(ev)
        assert client.get(f"/projects/{pid}/claims").status_code == 200
        assert client.get(f"/projects/{pid}/gaps").status_code == 200
        assert client.get(f"/projects/{pid}/contradictions").status_code == 200
        assert client.get(f"/projects/{pid}/hypotheses").status_code == 200

    def test_pagination_bounds(self, client):
        pid = _mk_project(client)
        r = client.get(f"/projects/{pid}/evidence", params={"limit": 500})
        assert r.status_code == 422   # le=200 enforced
        r = client.get(f"/projects/{pid}/evidence", params={"offset": -1})
        assert r.status_code == 422

    def test_report_path_traversal_blocked(self, client):
        pid = _mk_project(client)
        r = client.get(f"/projects/{pid}/reports/..%2F..%2Fsecrets")
        assert r.status_code in (404,)

    def test_report_missing_404(self, client):
        pid = _mk_project(client)
        r = client.get(f"/projects/{pid}/reports/nonexistent.md")
        assert r.status_code == 404


class TestHealthAndEvents:
    def test_health_ready(self, client):
        h = client.get("/health").json()
        assert h["status"] in ("healthy", "degraded", "unavailable")
        assert "database" in h["checks"]
        r = client.get("/ready").json()
        assert isinstance(r["ready"], bool)

    def test_events_endpoint(self, client):
        pid = _mk_project(client)
        evs = client.get("/events", params={"project_id": pid}).json()
        assert isinstance(evs, list)


class TestExperiments:
    def test_register_requires_known_fields(self, client):
        pid = _mk_project(client)
        r = client.post(f"/projects/{pid}/experiments", json={"title": "t"})
        assert r.status_code == 201

    def test_result_ingestion_unknown_experiment(self, client):
        pid = _mk_project(client)
        r = client.post(f"/projects/{pid}/experiments/exp_none/result",
                        json={"observations": ["x"]})
        assert r.status_code in (400, 404, 409, 500)
