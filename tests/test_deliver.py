import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import urllib.error
import urllib.request

import pytest

import deliver as deliver_module
from deliver import deliver, DeliveryError
from schema import DeliveryInfo, DeliveryStatus


class _FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b'{"ok": true}'


def test_deliver_skipped_when_url_empty(monkeypatch):
    monkeypatch.setenv("REVIEW_API_URL", "")

    def _boom(*args, **kwargs):
        raise AssertionError("HTTP must not be attempted when skipped")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    outcome = deliver("{}", submission_id="x", input_hash="y")
    assert outcome["outcome"] == "skipped"


def test_deliver_success(monkeypatch):
    monkeypatch.setenv("REVIEW_API_URL", "https://example.com/review")
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResponse())
    outcome = deliver("{}", submission_id="x", input_hash="y")
    assert outcome["outcome"] == "success"
    assert outcome["status_code"] == 200


def test_deliver_failed_non_retriable(monkeypatch):
    monkeypatch.setenv("REVIEW_API_URL", "https://example.com/review")

    def _raise(*args, **kwargs):
        raise urllib.error.HTTPError("https://example.com", 400, "Bad Request", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", _raise)
    with pytest.raises(DeliveryError) as exc:
        deliver("{}", submission_id="x", input_hash="y")
    assert exc.value.retriable is False
    assert exc.value.status_code == 400


def test_delivery_info_schema():
    info = DeliveryInfo(status=DeliveryStatus.SKIPPED, detail="REVIEW_API_URL not set")
    assert info.status.value == "skipped"
    dumped = info.model_dump()
    assert dumped["status"] == "skipped"


def test_deliver_fails_fast_when_max_attempts_is_one(monkeypatch):
    """ORION_DELIVERY_MAX_ATTEMPTS=1 should attempt once and not retry."""
    import importlib
    monkeypatch.setenv("REVIEW_API_URL", "https://example.com/review")
    monkeypatch.setenv("ORION_DELIVERY_MAX_ATTEMPTS", "1")
    importlib.reload(deliver_module)
    attempts = []

    def _raise_once(*args, **kwargs):
        attempts.append(1)
        raise urllib.error.HTTPError("https://example.com", 503, "Unavailable", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", _raise_once)
    with pytest.raises(deliver_module.DeliveryError):
        deliver_module.deliver("{}", submission_id="x", input_hash="y")
    assert len(attempts) == 1
