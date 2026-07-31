"""Thin SQLite persistence: latest assessment per submission + reviewer decisions.

Dual-written alongside audit.jsonl from the pipeline. DB path via ORION_DB_PATH
(default: data/orion.db). Write failures in the pipeline path are logged, never fatal.
"""

import json
import logging
import os
import sqlite3

log = logging.getLogger(__name__)


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
            notes TEXT
        )"""
    )
    return conn


def store_assessment(submission_id: str, assessed_at: str, result_json: str) -> None:
    """Upsert the latest assessment. Never raises — the pipeline must not break."""
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO assessments (submission_id, assessed_at, result_json) VALUES (?, ?, ?)",
                (submission_id, assessed_at, result_json),
            )
    except Exception as e:
        log.error(f"Failed to store assessment for '{submission_id}': {e}")


def get_assessment(submission_id: str) -> dict | None:
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


def store_review(submission_id: str, review: dict) -> None:
    """Persist a reviewer accept/override. Raises so the API can surface failure."""
    with _connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO reviews
               (submission_id, status, reviewer_id, reviewed_at, override_level, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                submission_id,
                review.get("status"),
                review.get("reviewer_id"),
                review.get("reviewed_at"),
                review.get("override_level"),
                review.get("notes"),
            ),
        )


def get_review(submission_id: str) -> dict | None:
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT status, reviewer_id, reviewed_at, override_level, notes FROM reviews WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "status": row[0],
            "reviewer_id": row[1],
            "reviewed_at": row[2],
            "override_level": row[3],
            "notes": row[4],
        }
    except Exception as e:
        log.error(f"Failed to read review for '{submission_id}': {e}")
        return None


def list_assessments() -> list[dict]:
    """Return the latest assessment for every submission, newest first."""
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT submission_id, result_json FROM assessments ORDER BY assessed_at DESC"
            ).fetchall()
        results = []
        for submission_id, result_json in rows:
            try:
                result = json.loads(result_json)
            except Exception as e:
                log.error(f"Failed to parse stored result for '{submission_id}': {e}")
                continue
            result["submission_id"] = submission_id
            results.append(result)
        return results
    except Exception as e:
        log.error(f"Failed to list assessments: {e}")
        return []
