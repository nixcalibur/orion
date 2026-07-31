import hashlib
import json
import logging
import os
import subprocess
from datetime import datetime, timezone

AUDIT_LOG_PATH = "audit.jsonl"

log = logging.getLogger(__name__)


def _commit_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def _hash_inputs(submission: dict, docs: dict) -> str:
    """Stable SHA-256 of all input content for reproducibility."""
    payload = json.dumps({"submission": submission, "docs": docs}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def write_audit_record(
    submission: dict,
    docs: dict,
    profile: dict,
    dim_scores: dict,
    composite: float,
    authorization: str,
    followup_questions: list,
    model: str,
    system_fingerprint: str = None,
    status: str = "success",
    prompt_hash: str = None,
    extraction_params: dict = None,
    delivery: dict = None,
    ingest_meta: dict = None,
):
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "submission_id": submission.get("submission_id"),
        "applicant_name": submission.get("applicant_name"),
        "input_hash": _hash_inputs(submission, docs),
        "commit_sha": _commit_sha(),
        "model": model,
        "system_fingerprint": system_fingerprint,
        "prompt_hash": prompt_hash or profile.get("_prompt_hash"),
        "extraction_params": extraction_params or profile.get("_extraction_params"),
        "extracted_profile": profile,
        "dimension_scores": dim_scores,
        "composite_score": composite,
        "authorization_level": authorization,
        "followup_questions": followup_questions,
        "delivery": delivery,
        "ingest": ingest_meta,
    }

    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")

    log.info(f"Audit record written → {AUDIT_LOG_PATH} (input_hash={record['input_hash'][:12]}...)")
