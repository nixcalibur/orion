"""Minimal HTTP surface over the SQLite store: health, latest assessment, review.

Run: uvicorn api:app --reload

Auth (optional): set ORION_API_KEY to require Bearer / X-API-Key on assessment routes.
Unset/empty keeps local open behavior. /health stays open.
"""

import json
import os
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException

from db import get_assessment, get_review, store_review
from schema import ReviewerOverride, ReviewStatus

app = FastAPI(title="ORION API")


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


@app.get("/assessments/{submission_id}", dependencies=[Depends(_check_api_key)])
def read_assessment(submission_id: str):
    result = get_assessment(submission_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    review = get_review(submission_id)
    if review:
        result["review"] = review
    return result


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
