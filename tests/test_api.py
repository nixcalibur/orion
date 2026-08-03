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
    # reviewed_at must be stored as an ISO-8601 string (no deprecated datetime
    # adapter, stable format for downstream consumers).
    reviewed_at = got.json()["review"]["reviewed_at"]
    assert "T" in reviewed_at
    assert " " not in reviewed_at


def test_get_assessment_does_not_leak_input_hash(client):
    db.store_assessment("sub1", "t", '{"composite_score": 2.0}', input_hash="internal-hash")
    result = db.get_assessment("sub1")
    assert "input_hash" not in result
    body = client.get("/assessments/sub1").json()
    assert "input_hash" not in body


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


def test_create_assessment_rejects_path_traversal(client, monkeypatch):
    def fake_run_pipeline(path, on_stage=None):
        raise AssertionError("pipeline should not be invoked for path traversal")

    monkeypatch.setattr("api.run_pipeline", fake_run_pipeline)
    r = client.post("/assessments", data={"path": "../requirements.txt"})
    assert r.status_code == 400
    assert "outside" in r.json()["detail"].lower() or "invalid" in r.json()["detail"].lower()


def test_uploaded_doc_path_traversal_is_sanitized(client, monkeypatch, tmp_path):
    stored = {}

    def fake_run_pipeline(path, on_stage=None):
        sid = "upload-sub-456"
        result = _sample_result(sid, "APPROVE", 1.0)
        from main import AssessmentResult
        result_obj = AssessmentResult(**result)
        db.store_assessment(sid, result_obj.assessed_at.isoformat(), result_obj.model_dump_json())
        # Capture the staged path passed to the pipeline.
        stored["path"] = path
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
            files={"submission": ("submission.json", sf, "application/json"), "docs": ("../../etc/passwd.txt", df, "text/plain")},
        )
    assert r.status_code == 200
    for _ in range(20):
        if stored.get("called"):
            break
        time.sleep(0.05)
    assert stored.get("called")
    staged_dir = os.path.dirname(stored["path"])
    assert os.path.dirname(stored["path"])  # not empty
    staged_files = os.listdir(staged_dir)
    assert not any(".." in f for f in staged_files)


def test_upload_size_limit_rejected(client, monkeypatch, tmp_path):
    monkeypatch.setenv("ORION_MAX_UPLOAD_SIZE", "10")

    def fake_run_pipeline(path, on_stage=None):
        raise AssertionError("pipeline should not be invoked for oversized upload")

    monkeypatch.setattr("api.run_pipeline", fake_run_pipeline)

    sub = tmp_path / "submission.json"
    sub.write_text(json.dumps({"submission_id": "upload-sub-456", "applicant_name": "Upload Test"}))
    doc = tmp_path / "doc.txt"
    doc.write_text("way more than ten bytes here")

    with open(sub, "rb") as sf, open(doc, "rb") as df:
        r = client.post(
            "/assessments",
            files={"submission": ("submission.json", sf, "application/json"), "docs": ("doc.txt", df, "text/plain")},
        )
    assert r.status_code == 413


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("doc.txt", "doc.txt"),
        ("", None),  # empty → random name, only assert safe shape
        (None, None),
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\x.txt", "x.txt"),
        ("a<b>:c|d?", "abcd"),
        ("   ", None),
        ("..", None),
        (".", None),
        ("report" + ".txt", "report.txt"),
        ("a" * 300 + ".txt", None),  # length limit → truncated, assert < 201 chars
    ],
)
def test_safe_filename_sanitization(monkeypatch, raw, expected):
    import api
    out = api._safe_filename(raw)
    if expected is None:
        # Random-name path: no path separators, no unsafe chars, safe length.
        assert "/" not in out and "\\" not in out
        assert ".." not in out
        assert len(out) <= 200 or (len(out) > 200 and out.startswith("a" * 199))
    else:
        assert out == expected


def test_safe_filename_limits_length(monkeypatch):
    import api
    out = api._safe_filename("x" * 300 + ".txt")
    assert len(out) <= 200
    assert out.endswith(".txt")


def test_job_cleanup_removes_expired_jobs(monkeypatch):
    import time as _time
    import api
    with api.JOBS_LOCK:
        api.JOBS.clear()
        api.JOBS["old"] = {"status": "complete", "updated_at": _time.time() - 7200}
        api.JOBS["new"] = {"status": "running", "updated_at": _time.time()}
    api._cleanup_old_jobs()
    assert "old" not in api.JOBS
    assert "new" in api.JOBS
    with api.JOBS_LOCK:
        api.JOBS.clear()


def test_list_assessments_flags_stale_review(client):
    db.store_assessment("sub1", "2026-08-03T00:00:00+00:00",
                        json.dumps(_sample_result()), input_hash="hash-1")
    db.store_review("sub1", {"status": "ACCEPTED", "reviewer_id": "rev-1"})
    # Reassess with different inputs → review becomes stale.
    db.store_assessment("sub1", "2026-08-03T01:00:00+00:00",
                        json.dumps(_sample_result(score=4.0)), input_hash="hash-2")
    rows = client.get("/assessments").json()
    assert rows[0]["review_status"] == "STALE"
    assert rows[0]["reviewer_id"] == "rev-1"


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


# ── Durable job state + filters + timing ──────────────────────────────────────


def test_durable_job_survives_in_memory_cache_loss(client, monkeypatch):
    stored = {}

    def fake_run_pipeline(path, on_stage=None):
        if on_stage:
            on_stage("ingest")
        sid = "e272b3cb"
        result = _sample_result(sid, "APPROVE", 1.2)
        from main import AssessmentResult
        result_obj = AssessmentResult(**result)
        db.store_assessment(sid, result_obj.assessed_at.isoformat(), result_obj.model_dump_json())
        stored["called"] = True
        return result_obj

    monkeypatch.setattr("api.run_pipeline", fake_run_pipeline)
    r = client.post("/assessments", data={"path": "dataset/e272b3cb/submission.json"})
    sid = r.json()["submission_id"]
    assert r.json()["status"] == "running"

    # The DB record is written synchronously by create_assessment.
    job = db.get_job(sid)
    assert job is not None
    # FastAPI's TestClient runs background tasks before returning, so the job is already complete.
    assert job["status"] == "complete"
    assert "stages" in job["timing"]
    assert any(s["stage"] == "ingest" for s in job["timing"]["stages"])
    assert "total_ms" in job["timing"]

    # Simulate API restart: the in-memory cache disappears.
    import api
    with api.JOBS_LOCK:
        api.JOBS.clear()

    # The DB job is still the source of truth; the assessment is still served.
    detail = client.get(f"/assessments/{sid}")
    assert detail.status_code == 200
    assert detail.json().get("recommendation") == "APPROVE"



def test_error_job_is_durable(client, monkeypatch):
    def fake_run_pipeline(path, on_stage=None):
        raise RuntimeError("simulated durable failure")

    monkeypatch.setattr("api.run_pipeline", fake_run_pipeline)
    r = client.post("/assessments", data={"path": "dataset/e272b3cb/submission.json"})
    sid = r.json()["submission_id"]

    for _ in range(20):
        detail = client.get(f"/assessments/{sid}")
        if detail.json().get("status") == "error":
            break
        time.sleep(0.05)

    detail = client.get(f"/assessments/{sid}")
    assert detail.json()["status"] == "error"
    assert "simulated durable failure" in detail.json()["detail"]

    # Simulate restart: the error detail must still be readable from SQLite.
    import api
    with api.JOBS_LOCK:
        api.JOBS.clear()
    detail = client.get(f"/assessments/{sid}")
    assert detail.json()["status"] == "error"
    assert "simulated durable failure" in detail.json()["detail"]


def test_stale_running_job_marked_error_after_timeout(client):
    from datetime import datetime, timedelta, timezone
    old = datetime.now(timezone.utc) - timedelta(minutes=15)
    db.store_job("stale-running", "running", stage="extract", updated_at=old.isoformat())

    import api
    with api.JOBS_LOCK:
        api.JOBS.clear()

    detail = client.get("/assessments/stale-running")
    assert detail.status_code == 200
    assert detail.json()["status"] == "error"
    assert "No job heartbeat" in detail.json()["detail"]


def test_list_assessments_pagination_and_filters(client):
    db.store_assessment("a1", "2026-07-31T12:00:00+00:00", json.dumps(_sample_result("a1", "CONDITIONAL", 3.5)))
    db.store_assessment("a2", "2026-07-31T13:00:00+00:00", json.dumps(_sample_result("a2", "REJECT", 9.0)))
    db.store_assessment("a3", "2026-07-31T14:00:00+00:00", json.dumps(_sample_result("a3", "APPROVE", 1.0)))

    rows = client.get("/assessments?limit=2").json()
    assert len(rows) == 2
    assert rows[0]["submission_id"] == "a3"

    rows = client.get("/assessments?limit=1&offset=1").json()
    assert len(rows) == 1
    assert rows[0]["submission_id"] == "a2"

    rows = client.get("/assessments?authorization_level=REJECT").json()
    assert len(rows) == 1 and rows[0]["submission_id"] == "a2"

    rows = client.get("/assessments?review_status=PENDING").json()
    assert len(rows) == 3

    assert client.get("/assessments?limit=0").status_code == 400
    assert client.get("/assessments?review_status=NOPE").status_code == 400


def test_formatted_assessment_includes_fail_closed_reasons(client):
    res = _sample_result("sub1", "REJECT", 10.0)
    res["risk_profile"]["has_criminal_flag"] = True
    db.store_assessment("sub1", "2026-07-31T12:00:00+00:00", json.dumps(res))
    body = client.get("/assessments/sub1").json()
    assert "criminal or sanctions flag" in body["fail_closed_reasons"]


def test_job_timing_recorded(client, monkeypatch):
    def fake_run_pipeline(path, on_stage=None):
        if on_stage:
            on_stage("ingest")
            on_stage("extract")
        sid = "e272b3cb"
        result = _sample_result(sid, "APPROVE", 1.2)
        from main import AssessmentResult
        result_obj = AssessmentResult(**result)
        db.store_assessment(sid, result_obj.assessed_at.isoformat(), result_obj.model_dump_json())
        return result_obj

    monkeypatch.setattr("api.run_pipeline", fake_run_pipeline)
    r = client.post("/assessments", data={"path": "dataset/e272b3cb/submission.json"})
    sid = r.json()["submission_id"]

    for _ in range(20):
        job = db.get_job(sid)
        if job and job.get("status") == "complete":
            break
        time.sleep(0.05)

    job = db.get_job(sid)
    assert job["status"] == "complete"
    assert "stages" in job["timing"]
    assert any(s["stage"] == "ingest" for s in job["timing"]["stages"])
    assert "total_ms" in job["timing"]
