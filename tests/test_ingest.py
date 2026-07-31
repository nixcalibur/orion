import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json

import pytest

import ingest as ingest_module


@pytest.fixture
def local_docs(monkeypatch, tmp_path):
    """Confine document reads to the test temp dir (default base is project root)."""
    monkeypatch.setattr(ingest_module, "ALLOWED_DOC_BASE", str(tmp_path))


def test_ingest_flags_truncated_document(tmp_path, monkeypatch, local_docs):
    monkeypatch.setattr(ingest_module, "DOC_CHAR_LIMIT", 50)
    doc = tmp_path / "big.txt"
    doc.write_text("x" * 500)
    sub = tmp_path / "submission.json"
    sub.write_text(json.dumps({"submission_id": "t1", "document_refs": [str(doc)]}))

    submission, docs, meta = ingest_module.ingest(str(sub))
    assert meta["truncated_docs"] == ["big.txt"]
    assert "TRUNCATED" in docs["big.txt"]


def test_ingest_no_flags_when_within_budget(tmp_path, local_docs):
    doc = tmp_path / "small.txt"
    doc.write_text("short")
    sub = tmp_path / "submission.json"
    sub.write_text(json.dumps({"submission_id": "t2", "document_refs": [str(doc)]}))

    _, docs, meta = ingest_module.ingest(str(sub))
    assert meta["truncated_docs"] == []
    assert meta["total_budget_trimmed"] is False


def test_ingest_standalone_document_autowrap(tmp_path, local_docs):
    doc = tmp_path / "policy.txt"
    doc.write_text("AML policy content")

    submission, docs, meta = ingest_module.ingest(str(doc))
    assert submission["document_refs"] == [str(doc)]
    assert docs["policy.txt"] == "AML policy content"
    assert submission["submission_id"]
    assert meta["truncated_docs"] == []


def test_ingest_blocks_path_traversal(tmp_path, local_docs):
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("secret contents")
    sub = tmp_path / "submission.json"
    sub.write_text(json.dumps({"submission_id": "t3", "document_refs": [str(outside)]}))

    _, docs, _ = ingest_module.ingest(str(sub))
    assert "BLOCKED" in docs["secret.txt"]
    assert "secret contents" not in docs["secret.txt"]
