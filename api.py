"""Minimal HTTP surface over the SQLite store: health, latest assessment, review.

Run: uvicorn api:app --reload

Auth (optional): set ORION_API_KEY to require Bearer / X-API-Key on assessment routes.
Unset/empty keeps local open behavior. /health stays open.
"""

import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from threading import Lock

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile

from db import get_assessment, get_review, list_assessments, store_review
from main import run_pipeline
from schema import ReviewerOverride, ReviewStatus

app = FastAPI(title="ORION API")

# In-memory job tracker for async pipeline runs. SQLite remains the durable store.
JOBS: dict[str, dict] = {}
JOBS_LOCK = Lock()

# Uploaded submissions are staged here, then passed to the pipeline by path.
UPLOAD_DIR = os.getenv("ORION_UPLOAD_DIR", "uploads")


def _check_api_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    """If ORION_API_KEY is set, require matching Bearer token or X-API-Key."""
    expected = os.getenv("ORION_API_KEY", "").strip()
    if not expected:
        return
    provided = (x_api_key or "").strip()
    if not provided and authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            provided = parts[1].strip()
    if provided != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
def health():
    return {"status": "ok", "service": "orion"}


def _friendly_summary(level: str, score: float, findings: list, hard_overrides: list) -> str:
    """One-sentence plain-language summary for a reviewer."""
    if hard_overrides:
        reasons = ", ".join(hard_overrides)
        return f"Recommendation is {level} because mandatory rules matched: {reasons}."
    if level == "APPROVE":
        return "The submission meets the standard review criteria with no material concerns."
    if level == "CONDITIONAL":
        return f"Authorization is possible but requires follow-up on {len(findings)} concern(s)."
    if level == "DEFER":
        return f"Significant gaps were found; the applicant should address {len(findings)} issue(s) before approval."
    return "Material risks or compliance failures were identified; authorization is not recommended."


def _format_assessment(result: dict) -> dict:
    """Wrap a raw pipeline result in a reviewer-friendly payload.

    Keeps the raw result available under the same top-level keys so existing
    API consumers are not broken; adds recommendation, summary, top_concerns,
    evidence_list, warnings, and review_status.
    """
    profile = result.get("risk_profile", {})
    dim_scores = result.get("dimension_scores", {})
    level = result.get("authorization_level", "")
    score = result.get("composite_score", 0.0)
    findings = result.get("key_findings", []) or []
    followups = result.get("followup_questions", []) or []
    missing = profile.get("missing_docs", []) or []

    hard_overrides = []
    if profile.get("has_criminal_flag"):
        hard_overrides.append("criminal or sanctions flag")
    if profile.get("regulatory_history") == "major_issues":
        hard_overrides.append("serious regulatory history")

    # High-scoring dimensions and missing documents become top concerns.
    top_concerns = []
    for dim, value in dim_scores.items():
        if dim == "missing_docs":
            continue
        if value and value >= 2:
            top_concerns.append(f"{dim.replace('_', ' ').title()}: score {value}")
    if missing:
        top_concerns.append(f"Missing documents: {', '.join(missing)}")
    if findings:
        for f in findings[:3]:
            if f not in top_concerns:
                top_concerns.append(f)

    evidence_list = []
    for dim, entry in (profile.get("evidence", {}) or {}).items():
        if not isinstance(entry, dict):
            continue
        evidence_list.append({
            "dimension": dim.replace("_", " ").title(),
            "source": entry.get("source_document"),
            "excerpt": entry.get("excerpt"),
            "supporting_details": entry.get("supporting_details"),
        })

    warnings = []
    ingest = result.get("ingest") or {}
    if ingest.get("truncated_docs"):
        warnings.append(f"Truncated documents: {', '.join(ingest['truncated_docs'])}")
    if ingest.get("total_budget_trimmed"):
        warnings.append("Total document size exceeded the budget; some evidence may be incomplete.")
    delivery = result.get("delivery") or {}
    if delivery.get("status") == "failed":
        warnings.append(f"External delivery failed: {delivery.get('detail')}")
    if delivery.get("status") == "skipped":
        warnings.append("External delivery was skipped.")

    review = result.get("review") or {}
    review_status = review.get("status", "PENDING")

    formatted = dict(result)
    formatted["recommendation"] = level
    formatted["summary"] = _friendly_summary(level, score, findings, hard_overrides)
    formatted["top_concerns"] = top_concerns
    formatted["evidence_list"] = evidence_list
    formatted["followup_questions"] = followups
    formatted["warnings"] = warnings
    formatted["review_status"] = review_status
    return formatted


def _run_pipeline_job(path: str, submission_id: str):
    """Background worker: run ORION pipeline and update the in-memory job record."""
    def on_stage(stage: str):
        with JOBS_LOCK:
            JOBS[submission_id] = {"status": "running", "stage": stage}

    try:
        result = run_pipeline(path, on_stage=on_stage)
        with JOBS_LOCK:
            if result is None:
                JOBS[submission_id] = {"status": "error", "detail": "Pipeline returned no result"}
            else:
                JOBS[submission_id] = {"status": "complete", "submission_id": submission_id}
    except Exception as e:
        with JOBS_LOCK:
            JOBS[submission_id] = {"status": "error", "detail": str(e)}


def _save_uploaded_submission(submission_file: UploadFile, docs: list[UploadFile]) -> str:
    """Stage an uploaded submission.json + supporting docs, return path to submission.json."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="orion_upload_", dir=UPLOAD_DIR)

    sub_path = os.path.join(workdir, "submission.json")
    with open(sub_path, "wb") as f:
        shutil.copyfileobj(submission_file.file, f)

    with open(sub_path, "r", encoding="utf-8") as f:
        submission = json.load(f)

    saved_doc_names = []
    for doc in docs:
        name = doc.filename or str(uuid.uuid4())
        dest = os.path.join(workdir, name)
        with open(dest, "wb") as f:
            shutil.copyfileobj(doc.file, f)
        saved_doc_names.append(name)

    # If the uploaded JSON already has document_refs, keep them as basenames so
    # they resolve to the staged directory.
    if submission.get("document_refs"):
        submission["document_refs"] = [
            os.path.basename(ref) for ref in submission["document_refs"]
        ]
    # If docs were uploaded but not referenced, append them.
    existing = set(submission.get("document_refs", []))
    for name in saved_doc_names:
        if name != "submission.json" and name not in existing:
            submission.setdefault("document_refs", []).append(name)

    with open(sub_path, "w", encoding="utf-8") as f:
        json.dump(submission, f)

    return sub_path


def _save_standalone_doc(doc: UploadFile) -> str:
    """Stage a single standalone document and return its path."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="orion_upload_", dir=UPLOAD_DIR)
    name = doc.filename or f"{uuid.uuid4()}.txt"
    dest = os.path.join(workdir, name)
    with open(dest, "wb") as f:
        shutil.copyfileobj(doc.file, f)
    return dest


def _save_multi_docs_as_submission(docs: list[UploadFile]) -> str:
    """Stage multiple loose documents as a single submission with generated metadata."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="orion_upload_", dir=UPLOAD_DIR)
    submission_id = os.path.basename(workdir).replace("orion_upload_", "")
    sub_path = os.path.join(workdir, "submission.json")
    doc_names = []
    for doc in docs:
        name = doc.filename or str(uuid.uuid4())
        dest = os.path.join(workdir, name)
        with open(dest, "wb") as f:
            shutil.copyfileobj(doc.file, f)
        doc_names.append(name)
    submission = {
        "submission_id": submission_id,
        "applicant_name": None,
        "document_refs": doc_names,
    }
    with open(sub_path, "w", encoding="utf-8") as f:
        json.dump(submission, f)
    return sub_path


@app.post("/assessments", dependencies=[Depends(_check_api_key)])
def create_assessment(
    background_tasks: BackgroundTasks,
    path: str | None = Form(default=None),
    submission: UploadFile | None = File(default=None),
    docs: list[UploadFile] = File(default=[]),
):
    """Start an ORION assessment.

    Options:
    - path: local submission.json or standalone document (dev/local use)
    - submission + docs: uploaded JSON metadata + supporting files
    - docs only: a single standalone document, or multiple loose documents
    """
    if path:
        run_path = path
        if path.lower().endswith(".json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    submission_id = json.load(f).get("submission_id") or os.path.splitext(os.path.basename(path))[0]
            except Exception:
                submission_id = os.path.splitext(os.path.basename(path))[0]
        else:
            submission_id = os.path.splitext(os.path.basename(path))[0]
    elif submission:
        if not docs:
            raise HTTPException(status_code=400, detail="At least one supporting document is required with submission.json")
        run_path = _save_uploaded_submission(submission, docs)
        try:
            with open(run_path, "r", encoding="utf-8") as f:
                submission_id = json.load(f).get("submission_id") or str(uuid.uuid4())[:8]
        except Exception:
            submission_id = str(uuid.uuid4())[:8]
    elif docs:
        if len(docs) == 1:
            run_path = _save_standalone_doc(docs[0])
            submission_id = os.path.splitext(os.path.basename(run_path))[0]
        else:
            run_path = _save_multi_docs_as_submission(docs)
            try:
                with open(run_path, "r", encoding="utf-8") as f:
                    submission_id = json.load(f).get("submission_id") or str(uuid.uuid4())[:8]
            except Exception:
                submission_id = str(uuid.uuid4())[:8]
    else:
        raise HTTPException(status_code=400, detail="Provide 'path' or upload 'submission'/'docs'")

    with JOBS_LOCK:
        JOBS[submission_id] = {"status": "running", "stage": "starting"}
    background_tasks.add_task(_run_pipeline_job, run_path, submission_id)

    return {"submission_id": submission_id, "status": "running", "stage": "starting"}


@app.get("/assessments", dependencies=[Depends(_check_api_key)])
def list_assessments_endpoint():
    rows = list_assessments()
    return [
        {
            "submission_id": r["submission_id"],
            "applicant_name": r.get("applicant_name"),
            "authorization_level": r.get("authorization_level"),
            "composite_score": r.get("composite_score"),
            "assessed_at": r.get("assessed_at"),
            "review_status": (r.get("review") or {}).get("status", "PENDING"),
            "reviewer_id": (r.get("review") or {}).get("reviewer_id"),
            "reviewed_at": (r.get("review") or {}).get("reviewed_at"),
        }
        for r in rows
    ]


@app.get("/assessments/{submission_id}", dependencies=[Depends(_check_api_key)])
def read_assessment(submission_id: str):
    # If the pipeline is still running or has failed, return the live job status.
    with JOBS_LOCK:
        job = JOBS.get(submission_id)
    if job:
        if job.get("status") == "running":
            return {"submission_id": submission_id, "status": "running", "stage": job.get("stage", "starting")}
        if job.get("status") == "error":
            return {
                "submission_id": submission_id,
                "status": "error",
                "stage": "error",
                "detail": job.get("detail", "Assessment failed"),
            }

    result = get_assessment(submission_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    review = get_review(submission_id)
    if review:
        result["review"] = review
    return _format_assessment(result)


@app.post("/assessments/{submission_id}/review", dependencies=[Depends(_check_api_key)])
def submit_review(submission_id: str, review: ReviewerOverride):
    if get_assessment(submission_id) is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if review.status == ReviewStatus.PENDING:
        raise HTTPException(status_code=400, detail="status must be ACCEPTED or OVERRIDDEN")
    if review.reviewed_at is None:
        review.reviewed_at = datetime.now(timezone.utc)
    store_review(submission_id, json.loads(review.model_dump_json()))
    return json.loads(review.model_dump_json())
