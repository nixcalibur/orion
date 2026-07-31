import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi.testclient import TestClient

import db


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ORION_DB_PATH", str(tmp_path / "test.db"))
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
