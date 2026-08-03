"""Thin SQLite persistence: latest assessment per submission + reviewer decisions.

Dual-written alongside audit.jsonl from the pipeline. DB path via ORION_DB_PATH
(default: data/orion.db). Write failures in the pipeline path are logged, never fatal.
"""

import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# SQLite identifiers are only ever constructed from this allowlist (DDL helpers).
_SQL_IDENTIFIER = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")


def _connect():
    db_path = os.getenv("ORION_DB_PATH", "data/orion.db")
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS assessments (
            submission_id TEXT PRIMARY KEY,
            assessed_at TEXT NOT NULL,
            applicant_name TEXT,
            authorization_level TEXT,
            composite_score REAL,
            input_hash TEXT,
            result_json TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS reviews (
            submission_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            reviewer_id TEXT,
            reviewed_at TEXT,
            override_level TEXT,
            notes TEXT,
            input_hash TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS jobs (
            submission_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            stage TEXT,
            detail TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            timing TEXT
        )"""
    )
    # Migrate older databases created before the new columns existed.
    _add_column_if_missing(conn, "assessments", "applicant_name", "TEXT")
    _add_column_if_missing(conn, "assessments", "authorization_level", "TEXT")
    _add_column_if_missing(conn, "assessments", "composite_score", "REAL")
    _add_column_if_missing(conn, "assessments", "input_hash", "TEXT")
    _add_column_if_missing(conn, "reviews", "input_hash", "TEXT")
    _add_column_if_missing(conn, "jobs", "timing", "TEXT")
    return conn


def _add_column_if_missing(conn, table, column, dtype):
    """Add a column if absent. Only allow-listed identifiers reach the SQL."""
    for name in (table, column, dtype):
        if not _SQL_IDENTIFIER.fullmatch(name):
            raise ValueError(f"Unsafe SQL identifier: {name!r}")
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {dtype}")


def store_assessment(
    submission_id: str,
    assessed_at: str,
    result_json: str,
    input_hash: str | None = None,
) -> None:
    """Upsert the latest assessment. Never raises — the pipeline must not break."""
    try:
        summary = json.loads(result_json)
    except Exception as e:
        log.warning(f"Failed to parse assessment JSON for metadata: {e}")
        summary = {}
    try:
        with _connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO assessments
                   (submission_id, assessed_at, applicant_name, authorization_level,
                    composite_score, input_hash, result_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    submission_id,
                    assessed_at,
                    summary.get("applicant_name"),
                    summary.get("authorization_level"),
                    summary.get("composite_score"),
                    input_hash or summary.get("input_hash"),
                    result_json,
                ),
            )
    except Exception as e:
        log.error(f"Failed to store assessment for '{submission_id}': {e}")


def store_job(
    submission_id: str,
    status: str,
    stage: str | None = None,
    detail: str | None = None,
    timing: dict | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> None:
    """Upsert a job record. Timing is stored as JSON."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _connect() as conn:
            # Preserve original created_at on updates.
            existing = conn.execute(
                "SELECT created_at FROM jobs WHERE submission_id = ?", (submission_id,)
            ).fetchone()
            conn.execute(
                """INSERT OR REPLACE INTO jobs
                   (submission_id, status, stage, detail, created_at, updated_at, timing)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    submission_id,
                    status,
                    stage,
                    detail,
                    created_at or (existing[0] if existing else now),
                    updated_at or now,
                    json.dumps(timing) if timing is not None else None,
                ),
            )
    except Exception as e:
        log.error(f"Failed to store job for '{submission_id}': {e}")


def get_job(submission_id: str) -> dict | None:
    """Return the durable job record for a submission, if any."""
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT status, stage, detail, created_at, updated_at, timing FROM jobs WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "submission_id": submission_id,
            "status": row[0],
            "stage": row[1],
            "detail": row[2],
            "created_at": row[3],
            "updated_at": row[4],
            "timing": json.loads(row[5]) if row[5] else None,
        }
    except Exception as e:
        log.error(f"Failed to read job for '{submission_id}': {e}")
        return None


def update_job_status(
    submission_id: str,
    status: str,
    stage: str | None = None,
    detail: str | None = None,
    timing: dict | None = None,
) -> None:
    """Merge updated timing into the existing job record and write to SQLite."""
    existing = get_job(submission_id)
    merged_timing = existing.get("timing") if existing else None
    if timing is not None:
        merged_timing = merged_timing or {}
        # Merge by overlay: callers send full or partial timing updates.
        merged_timing.update(timing)
    store_job(submission_id, status, stage=stage, detail=detail, timing=merged_timing)


def get_assessment(submission_id: str) -> dict | None:
    """Return the stored assessment result (no internal metadata like input_hash)."""
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT result_json FROM assessments WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None
    except Exception as e:
        log.error(f"Failed to read assessment for '{submission_id}': {e}")
        return None


def get_assessment_hash(submission_id: str) -> str | None:
    """Return the input_hash recorded with the latest assessment, if any."""
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT input_hash FROM assessments WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
        return row[0] if row else None
    except Exception as e:
        log.error(f"Failed to read assessment hash for '{submission_id}': {e}")
        return None


def _normalize_reviewed_at(value):
    """Store timestamps as ISO-8601 strings regardless of caller type."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def store_review(submission_id: str, review: dict) -> None:
    """Persist a reviewer accept/override. Raises so the API can surface failure.

    Derives the input_hash from the current assessment in the same connection.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT input_hash FROM assessments WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()
        input_hash = row[0] if row else None
        conn.execute(
            """INSERT OR REPLACE INTO reviews
               (submission_id, status, reviewer_id, reviewed_at, override_level, notes, input_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                submission_id,
                review.get("status"),
                review.get("reviewer_id"),
                _normalize_reviewed_at(review.get("reviewed_at")),
                review.get("override_level"),
                review.get("notes"),
                input_hash,
            ),
        )


def get_review(submission_id: str) -> dict | None:
    """Return the review for a submission.

    A review that predates a reassessment (input_hash mismatch) is returned with
    ``stale: True`` so callers can surface it instead of silently hiding it.
    """
    try:
        with _connect() as conn:
            row = conn.execute(
                """SELECT r.status, r.reviewer_id, r.reviewed_at, r.override_level, r.notes, r.input_hash,
                          a.input_hash
                   FROM reviews r
                   LEFT JOIN assessments a ON a.submission_id = r.submission_id
                   WHERE r.submission_id = ?""",
                (submission_id,),
            ).fetchone()
        if not row:
            return None
        review_hash, current_hash = row[5], row[6]
        review = {
            "status": row[0],
            "reviewer_id": row[1],
            "reviewed_at": row[2],
            "override_level": row[3],
            "notes": row[4],
        }
        if current_hash is not None and review_hash != current_hash:
            log.warning(
                f"Review for '{submission_id}' is stale (input_hash mismatch); flagging as stale."
            )
            review["stale"] = True
        return review
    except Exception as e:
        log.error(f"Failed to read review for '{submission_id}': {e}")
        return None


def list_assessments(
    limit: int = 100,
    offset: int = 0,
    authorization_level: str | None = None,
    review_status: str | None = None,
) -> list[dict]:
    """Return the latest assessment for every submission, newest first.

    Single LEFT JOIN avoids per-row connections. Uses stored metadata columns
    and only parses the full result JSON for legacy rows with missing columns.
    Supports pagination and optional filtering by authorization level or review
    status (PENDING, ACCEPTED, OVERRIDDEN, STALE).
    """
    try:
        # Compute the review-status filter in the query. The SQL is still a
        # single statement with the same LEFT JOIN structure; Python only filters
        # when a query parameter is provided.
        review_filter_sql = ""
        params: list = []
        if review_status:
            review_filter_sql = """AND (
                CASE
                    WHEN r.status IS NULL THEN 'PENDING'
                    WHEN a.input_hash IS NOT NULL AND r.input_hash IS NOT NULL AND a.input_hash != r.input_hash THEN 'STALE'
                    ELSE r.status
                END
            ) = ?"""
            params.append(review_status)
        level_filter_sql = ""
        if authorization_level:
            level_filter_sql = "AND a.authorization_level = ?"
            params.append(authorization_level)

        sql = f"""SELECT a.submission_id, a.applicant_name, a.authorization_level,
                          a.composite_score, a.assessed_at, a.result_json,
                          r.status, r.reviewer_id, r.reviewed_at, r.override_level,
                          r.notes, r.input_hash, a.input_hash
                   FROM assessments a
                   LEFT JOIN reviews r ON r.submission_id = a.submission_id
                   WHERE 1=1 {level_filter_sql} {review_filter_sql}
                   ORDER BY a.assessed_at DESC
                   LIMIT ? OFFSET ?"""
        params.extend([limit, offset])
        with _connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        results = []
        for row in rows:
            (submission_id, applicant_name, level, score, assessed_at, result_json,
             r_status, r_reviewer_id, r_reviewed_at, r_override_level, r_notes,
             r_input_hash, a_input_hash) = row
            result = {
                "submission_id": submission_id,
                "applicant_name": applicant_name,
                "authorization_level": level,
                "composite_score": score,
                "assessed_at": assessed_at,
            }
            if r_status is not None:
                review = {
                    "status": r_status,
                    "reviewer_id": r_reviewer_id,
                    "reviewed_at": r_reviewed_at,
                    "override_level": r_override_level,
                    "notes": r_notes,
                }
                if a_input_hash is not None and r_input_hash != a_input_hash:
                    review["stale"] = True
                result["review"] = review
            # Legacy rows (pre-migration) have NULL metadata columns; fill them
            # from the stored JSON. authorization_level/composite_score are never
            # legitimately NULL, so they identify those rows exactly.
            if level is None or score is None:
                try:
                    parsed = json.loads(result_json)
                except Exception as e:
                    log.error(f"Failed to parse stored result for '{submission_id}': {e}")
                    parsed = {}
                for key in ("applicant_name", "authorization_level", "composite_score"):
                    if result.get(key) is None:
                        result[key] = parsed.get(key)
            results.append(result)
        return results
    except Exception as e:
        log.error(f"Failed to list assessments: {e}")
        return []
