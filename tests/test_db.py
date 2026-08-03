import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import db


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    monkeypatch.setenv("ORION_DB_PATH", str(tmp_path / "test.db"))


def test_store_and_get_assessment(temp_db):
    db.store_assessment("sub1", "2026-07-30T00:00:00+00:00", '{"composite_score": 3.0}')
    result = db.get_assessment("sub1")
    assert result["composite_score"] == 3.0


def test_get_assessment_missing_returns_none(temp_db):
    assert db.get_assessment("nope") is None


def test_store_assessment_upserts_latest(temp_db):
    db.store_assessment("sub1", "t1", '{"v": 1}')
    db.store_assessment("sub1", "t2", '{"v": 2}')
    assert db.get_assessment("sub1")["v"] == 2


def test_store_and_get_review(temp_db):
    review = {
        "status": "ACCEPTED",
        "reviewer_id": "rev-1",
        "reviewed_at": "2026-07-30T00:00:00+00:00",
        "override_level": None,
        "notes": "looks fine",
    }
    db.store_review("sub1", review)
    stored = db.get_review("sub1")
    assert stored["reviewer_id"] == "rev-1"
    assert stored["status"] == "ACCEPTED"


def test_get_review_missing_returns_none(temp_db):
    assert db.get_review("nope") is None


def test_stale_review_is_invalidated_on_reassessment(temp_db):
    # First assessment + review
    db.store_assessment("sub1", "t1", '{"composite_score": 3.0}', input_hash="hash-1")
    db.store_review("sub1", {"status": "ACCEPTED", "reviewer_id": "rev-1"})
    assert db.get_review("sub1")["status"] == "ACCEPTED"

    # Reassessment with different inputs: review should be flagged as stale.
    db.store_assessment("sub1", "t2", '{"composite_score": 4.0}', input_hash="hash-2")
    review = db.get_review("sub1")
    assert review is not None
    assert review["stale"] is True
    assert review["status"] == "ACCEPTED"  # original decision still visible


def test_review_hash_matches_when_inputs_unchanged(temp_db):
    db.store_assessment("sub1", "t1", '{"composite_score": 3.0}', input_hash="hash-1")
    db.store_review("sub1", {"status": "ACCEPTED", "reviewer_id": "rev-1"})
    db.store_assessment("sub1", "t2", '{"composite_score": 3.0}', input_hash="hash-1")
    assert "stale" not in db.get_review("sub1")
