"""Minimal HTTP surface over the SQLite store: health, latest assessment, review.

Run: uvicorn api:app --reload

Auth (optional): set ORION_API_KEY to require Bearer / X-API-Key on assessment routes.
Unset/empty keeps local open behavior. /health stays open.
"""

import copy
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone
from threading import Lock

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile

from db import (
    get_assessment,
    get_job,
    get_review,
    list_assessments,
    store_job,
    store_review,
    update_job_status,
)
from ingest import _resolve_ref
from main import run_pipeline
from schema import ReviewerOverride, ReviewStatus

app = FastAPI(title="ORION API")

# In-memory job tracker for async pipeline runs. SQLite remains the durable store.
JOBS: dict[str, dict] = {}
JOBS_LOCK = Lock()
# Completed/error jobs are retained for this many minutes before cleanup.
JOB_TTL_MINUTES = int(os.getenv("ORION_JOB_TTL_MINUTES", "60"))

# Uploaded submissions are staged here, then passed to the pipeline by path.
UPLOAD_DIR = os.getenv("ORION_UPLOAD_DIR", "uploads")
# Maximum size for any uploaded file in bytes (default 50 MB).
DEFAULT_MAX_UPLOAD_SIZE = 50 * 1024 * 1024


def _safe_filename(filename: str | None) -> str:
    """Strip path traversal and unsafe characters from uploaded filenames.

    Returns a random UUID name if the filename is empty or entirely unsafe.
    Enforces a 200-char limit to stay within common filesystem limits.
    """
    if not filename:
        return f"{uuid.uuid4()}.bin"
    base = os.path.basename(filename.replace("\\", "/"))
    base = re.sub(r'[<>:"|?*\x00-\x1f]', "", base)
    base = base.strip(". ")
    if not base or base in {"..", "."}:
        return f"{uuid.uuid4()}.bin"
    if len(base) > 200:
        name, ext = os.path.splitext(base)
        base = name[: 200 - len(ext)] + ext if len(ext) < 200 else base[:200]
    return base


def _check_upload_size(doc: UploadFile):
    """Reject uploads larger than ORION_MAX_UPLOAD_SIZE (default 50 MB).

    Uses UploadFile.size if available; otherwise falls back to reading the file.
    """
    max_size = int(os.getenv("ORION_MAX_UPLOAD_SIZE", str(DEFAULT_MAX_UPLOAD_SIZE)))
    if hasattr(doc, "size") and doc.size is not None:
        size = doc.size
    else:
        # Fall back: read the whole file into memory. This is acceptable for the
        # default size cap and the FastAPI test client.
        doc.file.seek(0, os.SEEK_END)
        size = doc.file.tell()
        doc.file.seek(0)
    if size > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"Upload exceeds maximum size of {max_size} bytes",
        )


def _cleanup_old_jobs():
    """Remove completed/error jobs older than JOB_TTL_MINUTES."""
    cutoff = time.time() - JOB_TTL_MINUTES * 60
    stale = [sid for sid, job in JOBS.items() if job.get("updated_at", cutoff + 1) < cutoff]
    for sid in stale:
        JOBS.pop(sid, None)


# Cleanup is throttled: run at most once per CLEANUP_INTERVAL on the write path.
_LAST_CLEANUP = 0.0
CLEANUP_INTERVAL = 60  # seconds


def _update_job(submission_id: str, **kwargs):
    """Update the in-memory job cache and durably persist it to SQLite."""
    global _LAST_CLEANUP
    now = time.time()
    now_iso = datetime.now(timezone.utc).isoformat()
    with JOBS_LOCK:
        if now - _LAST_CLEANUP > CLEANUP_INTERVAL:
            _cleanup_old_jobs()
            _LAST_CLEANUP = now
        job = JOBS.get(submission_id, {})
        job.update(kwargs)
        job["updated_at"] = now
        JOBS[submission_id] = job

    # Durable mirror. Timing is merged; other fields overwrite.
    timing = job.get("timing")
    try:
        update_job_status(
            submission_id,
            status=job.get("status"),
            stage=job.get("stage"),
            detail=job.get("detail"),
            timing=timing,
        )
    except Exception:
        # Never let the DB mirror break the API response path.
        pass


def _get_job(submission_id: str) -> dict | None:
    """Return the current job, preferring the in-memory cache but falling back to SQLite.

    Stale running jobs (no heartbeat longer than ORION_RUNNING_JOB_TIMEOUT_MINUTES)
    are marked as error so restarts do not leave assessments stuck in 'running'.
    """
    with JOBS_LOCK:
        job = JOBS.get(submission_id)
    if job:
        return job
    job = get_job(submission_id)
    if job is None:
        return None
    if job.get("status") == "running":
        timeout_min = int(os.getenv("ORION_RUNNING_JOB_TIMEOUT_MINUTES", "10"))
        updated = job.get("updated_at")
        if updated:
            try:
                from datetime import datetime as _dt
                updated_ts = _dt.fromisoformat(updated).timestamp()
            except Exception:
                updated_ts = 0
            if time.time() - updated_ts > timeout_min * 60:
                detail = f"No job heartbeat for {timeout_min} minutes (process may have restarted)."
                _update_job(submission_id, status="error", stage="error", detail=detail)
                return JOBS.get(submission_id, {**job, "status": "error", "detail": detail})
    return job


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
    review_status = "STALE" if review.get("stale") else review.get("status", "PENDING")

    formatted = copy.deepcopy(result)
    formatted["recommendation"] = level
    formatted["summary"] = _friendly_summary(level, score, findings, hard_overrides)
    formatted["top_concerns"] = top_concerns
    formatted["evidence_list"] = evidence_list
    formatted["followup_questions"] = followups
    formatted["warnings"] = warnings
    formatted["review_status"] = review_status
    # Visible product differentiator: show when mandatory rules drove the outcome.
    formatted["fail_closed_reasons"] = hard_overrides
    return formatted


def _run_pipeline_job(path: str, submission_id: str):
    """Background worker: run ORION pipeline and durably track job state + timing."""
    started_at = time.time()
    timing = {"started_at": datetime.now(timezone.utc).isoformat(), "stages": []}
    _update_job(submission_id, status="running", stage="starting", timing=timing)

    def on_stage(stage: str):
        elapsed_ms = int((time.time() - started_at) * 1000)
        timing["stages"].append({"stage": stage, "elapsed_ms": elapsed_ms})
        _update_job(submission_id, status="running", stage=stage, timing=timing)

    try:
        result = run_pipeline(path, on_stage=on_stage)
        timing["completed_at"] = datetime.now(timezone.utc).isoformat()
        timing["total_ms"] = int((time.time() - started_at) * 1000)
        if result is None:
            _update_job(
                submission_id,
                status="error",
                stage="error",
                detail="Pipeline returned no result",
                timing=timing,
            )
        else:
            _update_job(submission_id, status="complete", stage="complete", timing=timing)
    except Exception as e:
        timing["completed_at"] = datetime.now(timezone.utc).isoformat()
        timing["total_ms"] = int((time.time() - started_at) * 1000)
        _update_job(submission_id, status="error", stage="error", detail=str(e), timing=timing)


def _save_uploaded_submission(submission_file: UploadFile, docs: list[UploadFile]) -> str:
    """Stage an uploaded submission.json + supporting docs, return path to submission.json."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="orion_upload_", dir=UPLOAD_DIR)

    _check_upload_size(submission_file)
    sub_path = os.path.join(workdir, "submission.json")
    with open(sub_path, "wb") as f:
        shutil.copyfileobj(submission_file.file, f)

    with open(sub_path, "r", encoding="utf-8") as f:
        submission = json.load(f)

    # Map the raw uploaded basename to its sanitized saved name so document_refs
    # that referenced the original name still resolve to the staged copy.
    raw_to_saved: dict[str, str] = {}
    saved_doc_names = []
    used_names = {"submission.json"}
    for doc in docs:
        _check_upload_size(doc)
        name = _safe_filename(doc.filename)
        # Guard against duplicate sanitized names in the same upload.
        if name in used_names:
            name = f"{uuid.uuid4()}_{name}"
        used_names.add(name)
        dest = os.path.join(workdir, name)
        with open(dest, "wb") as f:
            shutil.copyfileobj(doc.file, f)
        raw_base = os.path.basename((doc.filename or "").replace("\\", "/"))
        if raw_base:
            raw_to_saved[raw_base] = name
        saved_doc_names.append(name)

    # Rewrite document_refs to the sanitized saved names so they resolve to the
    # staged directory. Unuploaded refs keep their basename (the pipeline will
    # mark them MISSING, as before).
    if submission.get("document_refs"):
        submission["document_refs"] = [
            raw_to_saved.get(os.path.basename(ref.replace("\\", "/")), os.path.basename(ref))
            for ref in submission["document_refs"]
        ]
    # If docs were uploaded but not referenced, append them.
    existing = set(submission.get("document_refs", []))
    for name in saved_doc_names:
        if name not in existing:
            submission.setdefault("document_refs", []).append(name)

    with open(sub_path, "w", encoding="utf-8") as f:
        json.dump(submission, f)

    return sub_path


def _save_standalone_doc(doc: UploadFile) -> str:
    """Stage a single standalone document and return its path."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="orion_upload_", dir=UPLOAD_DIR)
    _check_upload_size(doc)
    name = _safe_filename(doc.filename)
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
    used_names = set()
    for doc in docs:
        _check_upload_size(doc)
        name = _safe_filename(doc.filename)
        if name in used_names:
            name = f"{uuid.uuid4()}_{name}"
        used_names.add(name)
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
        # Reject paths that escape the configured docs directory.
        try:
            run_path = _resolve_ref(path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid path: {e}")
        if run_path.lower().endswith(".json"):
            try:
                with open(run_path, "r", encoding="utf-8") as f:
                    submission_id = json.load(f).get("submission_id") or os.path.splitext(os.path.basename(run_path))[0]
            except Exception:
                submission_id = os.path.splitext(os.path.basename(run_path))[0]
        else:
            submission_id = os.path.splitext(os.path.basename(run_path))[0]
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

    _update_job(submission_id, status="running", stage="starting")
    background_tasks.add_task(_run_pipeline_job, run_path, submission_id)

    return {"submission_id": submission_id, "status": "running", "stage": "starting"}


@app.get("/assessments", dependencies=[Depends(_check_api_key)])
def list_assessments_endpoint(
    limit: int = 100,
    offset: int = 0,
    authorization_level: str | None = None,
    review_status: str | None = None,
):
    """List assessments with pagination and optional filters.

    - limit: 1–500 (default 100)
    - offset: 0+ (default 0)
    - authorization_level: APPROVE | CONDITIONAL | DEFER | REJECT
    - review_status: PENDING | ACCEPTED | OVERRIDDEN | STALE
    """
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    if authorization_level and authorization_level not in ("APPROVE", "CONDITIONAL", "DEFER", "REJECT"):
        raise HTTPException(status_code=400, detail="invalid authorization_level")
    if review_status and review_status not in ("PENDING", "ACCEPTED", "OVERRIDDEN", "STALE"):
        raise HTTPException(status_code=400, detail="invalid review_status")

    rows = list_assessments(
        limit=limit,
        offset=offset,
        authorization_level=authorization_level,
        review_status=review_status,
    )
    return [
        {
            "submission_id": r["submission_id"],
            "applicant_name": r.get("applicant_name"),
            "authorization_level": r.get("authorization_level"),
            "composite_score": r.get("composite_score"),
            "assessed_at": r.get("assessed_at"),
            "review_status": ("STALE" if (r.get("review") or {}).get("stale")
                              else (r.get("review") or {}).get("status", "PENDING")),
            "reviewer_id": (r.get("review") or {}).get("reviewer_id"),
            "reviewed_at": (r.get("review") or {}).get("reviewed_at"),
        }
        for r in rows
    ]


@app.get("/assessments/{submission_id}", dependencies=[Depends(_check_api_key)])
def read_assessment(submission_id: str):
    # If the pipeline is still running or has failed, return the live job status.
    # The durable DB record is the source of truth, with an in-memory cache for
    # fast polling; _get_job handles both and detects stale running jobs.
    job = _get_job(submission_id)
    if job:
        if job.get("status") == "running":
            return {
                "submission_id": submission_id,
                "status": "running",
                "stage": job.get("stage", "starting"),
            }
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
    # mode="json" yields ISO-8601 strings (not datetime objects), so SQLite gets
    # the same format the pipeline stores elsewhere and no adapter is required.
    review_data = review.model_dump(mode="json")
    store_review(submission_id, review_data)
    return review_data
