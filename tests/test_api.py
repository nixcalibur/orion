import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import time
import json

import pytest
from fastapi.testclient import TestClient

import db


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ORION_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("ORION_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("ORION_API_KEY", raising=False)
    from api import app
    with TestClient(app) as c:
        yield c


def test_health(client):
    assert client.get("/health").status_code == 200


def test_assessment_not_found(client):
    assert client.get("/assessments/nope").status_code == 404


def test_review_requires_existing_assessment(client):
    r = client.post(
        "/assessments/nope/review",
        json={"status": "ACCEPTED", "reviewer_id": "rev-1"},
    )
    assert r.status_code == 404


def test_review_rejects_pending(client):
    db.store_assessment("sub1", "t", '{"composite_score": 2.0}')
    r = client.post("/assessments/sub1/review", json={"status": "PENDING"})
    assert r.status_code == 400


def test_review_roundtrip(client):
    db.store_assessment("sub1", "t", '{"composite_score": 2.0}')
    r = client.post(
        "/assessments/sub1/review",
        json={"status": "OVERRIDDEN", "reviewer_id": "rev-1", "override_level": "APPROVE"},
    )
    assert r.status_code == 200
    assert r.json()["reviewer_id"] == "rev-1"
    got = client.get("/assessments/sub1")
    assert got.json()["review"]["status"] == "OVERRIDDEN"


def test_open_mode_when_api_key_unset(client):
    """No ORION_API_KEY → assessment routes stay open (dev-friendly)."""
    db.store_assessment("sub1", "t", '{"composite_score": 2.0}')
    assert client.get("/assessments/sub1").status_code == 200
    assert client.get("/health").status_code == 200


def test_api_key_required_when_configured(client, monkeypatch):
    monkeypatch.setenv("ORION_API_KEY", "secret-key")
    db.store_assessment("sub1", "t", '{"composite_score": 2.0}')

    assert client.get("/health").status_code == 200  # health stays open
    assert client.get("/assessments/sub1").status_code == 401
    assert client.get("/assessments/sub1", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/assessments/sub1", headers={"Authorization": "Bearer wrong"}).status_code == 401

    assert client.get("/assessments/sub1", headers={"X-API-Key": "secret-key"}).status_code == 200
    assert client.get("/assessments/sub1", headers={"Authorization": "Bearer secret-key"}).status_code == 200

    r = client.post(
        "/assessments/sub1/review",
        json={"status": "ACCEPTED", "reviewer_id": "rev-1"},
    )
    assert r.status_code == 401
    r = client.post(
        "/assessments/sub1/review",
        headers={"X-API-Key": "secret-key"},
        json={"status": "ACCEPTED", "reviewer_id": "rev-1"},
    )
    assert r.status_code == 200


# ── New reviewer-experience endpoints ─────────────────────────────────────────


def _sample_result(submission_id="sub1", level="CONDITIONAL", score=3.5):
    return {
        "submission_id": submission_id,
        "applicant_name": "Test Applicant",
        "assessed_at": "2026-07-31T12:00:00+00:00",
        "authorization_level": level,
        "composite_score": score,
        "dimension_scores": {"ownership": 2, "aml_present": 0, "missing_docs": 1},
        "risk_profile": {
            "ownership": "complex",
            "aml_present": True,
            "regulatory_history": "clean",
            "cyber": "adequate",
            "financial_health": "healthy",
            "privacy": "compliant",
            "has_pep": False,
            "has_criminal_flag": False,
            "missing_docs": ["audited financials"],
            "key_findings": ["Ownership is multi-layered."],
            "evidence": {
                "ownership": {
                    "source_document": "structure.txt",
                    "excerpt": "Owned by a holding company in Cyprus.",
                }
            },
        },
        "followup_questions": ["Please provide audited financials."],
        "key_findings": ["Ownership is multi-layered."],
        "ingest": {"truncated_docs": [], "total_budget_trimmed": False},
    }


def test_list_assessments_empty(client):
    assert client.get("/assessments").json() == []


def test_list_assessments_returns_summary(client):
    db.store_assessment("sub1", "2026-07-31T12:00:00+00:00", json.dumps(_sample_result()))
    rows = client.get("/assessments").json()
    assert len(rows) == 1
    assert rows[0]["submission_id"] == "sub1"
    assert rows[0]["authorization_level"] == "CONDITIONAL"
    assert rows[0]["composite_score"] == 3.5
    assert rows[0]["review_status"] == "PENDING"


def test_formatted_assessment_includes_reviewer_friendly_fields(client):
    db.store_assessment("sub1", "2026-07-31T12:00:00+00:00", json.dumps(_sample_result()))
    r = client.get("/assessments/sub1")
    assert r.status_code == 200
    body = r.json()
    assert body["recommendation"] == "CONDITIONAL"
    assert "summary" in body
    assert "top_concerns" in body
    assert any("Ownership" in c for c in body["top_concerns"])
    assert body["evidence_list"][0]["dimension"] == "Ownership"
    assert body["followup_questions"] == ["Please provide audited financials."]
    assert body["review_status"] == "PENDING"


def test_create_assessment_with_path(client, monkeypatch):
    stored = {}

    def fake_run_pipeline(path, on_stage=None):
        sid = "e272b3cb"  # submission_id inside the JSON file used in this test
        if on_stage:
            on_stage("ingest")
        result = _sample_result(sid, "APPROVE", 1.2)
        from main import AssessmentResult, ReviewerOverride, ReviewStatus
        result_obj = AssessmentResult(**result)
        db.store_assessment(sid, result_obj.assessed_at.isoformat(), result_obj.model_dump_json())
        stored["called"] = True
        return result_obj

    monkeypatch.setattr("api.run_pipeline", fake_run_pipeline)
    r = client.post("/assessments", data={"path": "dataset/e272b3cb/submission.json"})
    assert r.status_code == 200
    assert r.json()["status"] == "running"
    assert r.json()["stage"] == "starting"
    submission_id = r.json()["submission_id"]
    assert submission_id == "e272b3cb"

    # Background tasks run after the response in TestClient; small wait for completion.
    for _ in range(20):
        if stored.get("called"):
            break
        time.sleep(0.05)
    assert stored.get("called")

    detail = client.get(f"/assessments/{submission_id}")
    assert detail.status_code == 200
    assert detail.json()["recommendation"] == "APPROVE"


def test_create_assessment_with_file_upload(client, monkeypatch, tmp_path):
    stored = {}

    def fake_run_pipeline(path, on_stage=None):
        sid = "upload-sub-456"
        if on_stage:
            on_stage("extract")
        result = _sample_result(sid, "DEFER", 5.5)
        from main import AssessmentResult, ReviewerOverride, ReviewStatus
        result_obj = AssessmentResult(**result)
        db.store_assessment(sid, result_obj.assessed_at.isoformat(), result_obj.model_dump_json())
        stored["called"] = True
        return result_obj

    monkeypatch.setattr("api.run_pipeline", fake_run_pipeline)

    sub = tmp_path / "submission.json"
    sub.write_text(json.dumps({"submission_id": "upload-sub-456", "applicant_name": "Upload Test"}))
    doc = tmp_path / "doc.txt"
    doc.write_text("Some evidence.")

    with open(sub, "rb") as sf, open(doc, "rb") as df:
        r = client.post(
            "/assessments",
            files={"submission": ("submission.json", sf, "application/json"), "docs": ("doc.txt", df, "text/plain")},
        )
    assert r.status_code == 200
    submission_id = r.json()["submission_id"]

    for _ in range(20):
        if stored.get("called"):
            break
        time.sleep(0.05)
    assert stored.get("called")

    detail = client.get(f"/assessments/{submission_id}")
    assert detail.status_code == 200
    assert detail.json()["recommendation"] == "DEFER"


def test_create_assessment_rejects_empty_request(client):
    r = client.post("/assessments")
    assert r.status_code == 400


def test_running_job_returns_status_and_stage(client, monkeypatch):
    stored = {}
    stages = []

    def fake_run_pipeline(path, on_stage=None):
        if on_stage:
            on_stage("ingest")
            stages.append("ingest")
        time.sleep(0.1)  # small delay to exercise the running state path
        sid = "e272b3cb"
        result = _sample_result(sid, "APPROVE", 1.2)
        from main import AssessmentResult, ReviewerOverride, ReviewStatus
        result_obj = AssessmentResult(**result)
        db.store_assessment(sid, result_obj.assessed_at.isoformat(), result_obj.model_dump_json())
        stored["called"] = True
        return result_obj

    monkeypatch.setattr("api.run_pipeline", fake_run_pipeline)
    r = client.post("/assessments", data={"path": "dataset/e272b3cb/submission.json"})
    sid = r.json()["submission_id"]
    assert r.json()["status"] == "running"
    assert r.json()["stage"] == "starting"

    # The GET may catch the job while it is still running.
    detail = client.get(f"/assessments/{sid}")
    assert detail.status_code == 200
    if detail.json().get("status") == "running":
        assert "stage" in detail.json()
    else:
        assert detail.json()["recommendation"] == "APPROVE"

    for _ in range(20):
        if stored.get("called"):
            break
        time.sleep(0.05)
    assert stored.get("called")
    assert "ingest" in stages


def test_failed_job_returns_error_not_404(client, monkeypatch):
    def fake_run_pipeline(path, on_stage=None):
        raise RuntimeError("simulated extraction failure")

    monkeypatch.setattr("api.run_pipeline", fake_run_pipeline)
    r = client.post("/assessments", data={"path": "dataset/e272b3cb/submission.json"})
    sid = r.json()["submission_id"]
    assert r.json()["status"] == "running"

    for _ in range(20):
        detail = client.get(f"/assessments/{sid}")
        if detail.json().get("status") == "error":
            break
        time.sleep(0.05)

    detail = client.get(f"/assessments/{sid}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "error"
    assert body["stage"] == "error"
    assert "simulated extraction failure" in body["detail"]


def test_failed_pipeline_return_none_returns_error(client, monkeypatch):
    def fake_run_pipeline(path, on_stage=None):
        return None

    monkeypatch.setattr("api.run_pipeline", fake_run_pipeline)
    r = client.post("/assessments", data={"path": "dataset/e272b3cb/submission.json"})
    sid = r.json()["submission_id"]

    for _ in range(20):
        detail = client.get(f"/assessments/{sid}")
        if detail.json().get("status") == "error":
            break
        time.sleep(0.05)

    detail = client.get(f"/assessments/{sid}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "error"
    assert "Pipeline returned no result" in detail.json()["detail"]
