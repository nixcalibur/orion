import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="ORION API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

AUDIT_LOG = "audit.jsonl"
DATASET_DIR = "dataset"

_job_status: dict = {}   # submission_id -> "processing" | "complete" | "error"
_reviews: dict = {}      # submission_id -> review dict


def _read_audit_records() -> list:
    if not os.path.exists(AUDIT_LOG):
        return []
    records = []
    with open(AUDIT_LOG) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def _read_submission_meta(submission_id: str) -> dict:
    path = Path(DATASET_DIR) / submission_id / "submission.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def _run_pipeline_job(submission_id: str, submission_path: str) -> None:
    try:
        from main import run_pipeline
        result = run_pipeline(submission_path)
        _job_status[submission_id] = "complete" if result else "error"
    except Exception:
        _job_status[submission_id] = "error"


@app.post("/api/submissions")
async def create_submission(
    submission_file: UploadFile = File(...),
    documents: List[UploadFile] = File(default=[]),
):
    content = await submission_file.read()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="submission_file must be valid JSON")

    submission_id = data.get("submission_id") or str(uuid.uuid4())[:8]
    data["submission_id"] = submission_id

    sub_dir = Path(DATASET_DIR) / submission_id
    docs_dir = sub_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    doc_refs = list(data.get("document_refs", []))
    for doc in documents:
        doc_bytes = await doc.read()
        dest = docs_dir / doc.filename
        dest.write_bytes(doc_bytes)
        ref = str(dest)
        if ref not in doc_refs:
            doc_refs.append(ref)

    data["document_refs"] = doc_refs
    submission_path = sub_dir / "submission.json"
    submission_path.write_text(json.dumps(data, indent=2))

    _job_status[submission_id] = "processing"
    threading.Thread(
        target=_run_pipeline_job,
        args=(submission_id, str(submission_path)),
        daemon=True,
    ).start()

    return {"submission_id": submission_id, "status": "processing"}


@app.get("/api/submissions")
def list_submissions():
    records = _read_audit_records()
    summaries = []
    seen: set = set()

    for r in reversed(records):
        sid = r.get("submission_id")
        if sid in seen:
            continue
        seen.add(sid)
        meta = _read_submission_meta(sid) if sid else {}
        summaries.append({
            "submission_id": sid,
            "assessed_at": r.get("timestamp"),
            "authorization_level": r.get("authorization_level") or None,
            "composite_score": r.get("composite_score"),
            "applicant_name": r.get("applicant_name"),
            "jurisdiction": meta.get("jurisdiction"),
            "status": r.get("status") or "complete",
        })

    summaries.sort(key=lambda x: x.get("assessed_at") or "", reverse=True)

    for sid, st in _job_status.items():
        if sid not in seen and st == "processing":
            summaries.insert(0, {
                "submission_id": sid,
                "assessed_at": None,
                "authorization_level": None,
                "composite_score": None,
                "applicant_name": None,
                "jurisdiction": None,
                "status": "processing",
            })

    return summaries


@app.get("/api/submissions/{submission_id}/status")
def get_submission_status(submission_id: str):
    if submission_id in _job_status:
        return {"submission_id": submission_id, "status": _job_status[submission_id]}
    for r in reversed(_read_audit_records()):
        if r.get("submission_id") == submission_id:
            return {"submission_id": submission_id, "status": r.get("status") or "complete"}
    return {"submission_id": submission_id, "status": "unknown"}


@app.get("/api/submissions/{submission_id}")
def get_submission(submission_id: str):
    record = None
    for r in reversed(_read_audit_records()):
        if r.get("submission_id") == submission_id:
            record = r
            break
    if not record:
        raise HTTPException(status_code=404, detail="Submission not found")

    meta = _read_submission_meta(submission_id)
    profile = record.get("extracted_profile", {})

    return {
        **record,
        "jurisdiction": meta.get("jurisdiction"),
        "declared_activities": meta.get("declared_activities", []),
        "key_personnel": meta.get("key_personnel", []),
        "incorporation_date": meta.get("incorporation_date"),
        "activities_verified": profile.get("activities_verified", []),
        "activities_undeclared": profile.get("activities_undeclared", []),
        "key_findings": profile.get("key_findings", []),
        "review": _reviews.get(submission_id),
    }


@app.post("/api/submissions/{submission_id}/review")
async def submit_review(submission_id: str, request: Request):
    body = await request.json()
    action = body.get("action")
    if action not in ("accept", "override"):
        raise HTTPException(status_code=400, detail="action must be 'accept' or 'override'")
    reviewer_id = (body.get("reviewer_id") or "").strip()
    if not reviewer_id:
        raise HTTPException(status_code=400, detail="reviewer_id required")

    review = {
        "status": "ACCEPTED" if action == "accept" else "OVERRIDDEN",
        "reviewer_id": reviewer_id,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "override_level": body.get("override_level"),
        "notes": body.get("notes"),
    }
    _reviews[submission_id] = review
    return review


@app.get("/api/stats")
def get_stats():
    records = _read_audit_records()
    if not records:
        return {
            "total": 0,
            "by_level": {},
            "avg_score": 0,
            "with_followups": 0,
            "pending_review": 0,
            "rejection_rate": 0,
            "recent_7d": [],
        }

    total = len(records)
    level_counts: dict = {}
    score_sum = 0.0
    with_followups = 0
    pending_review = 0

    for r in records:
        level = r.get("authorization_level") or "unknown"
        level_counts[level] = level_counts.get(level, 0) + 1
        score_sum += r.get("composite_score") or 0.0
        if r.get("followup_questions"):
            with_followups += 1
        if level in ("CONDITIONAL", "DEFER"):
            pending_review += 1

    by_level = {
        level: {"count": count, "pct": round(count / total * 100, 1)}
        for level, count in level_counts.items()
    }

    now = datetime.now(timezone.utc)
    trend: dict = {}
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        trend[day] = 0
    for r in records:
        day = (r.get("timestamp") or "")[:10]
        if day in trend:
            trend[day] += 1

    reject_count = level_counts.get("REJECT", 0)

    return {
        "total": total,
        "by_level": by_level,
        "avg_score": round(score_sum / total, 2),
        "with_followups": with_followups,
        "pending_review": pending_review,
        "rejection_rate": round(reject_count / total * 100, 1),
        "recent_7d": [{"date": d, "count": c} for d, c in trend.items()],
    }
