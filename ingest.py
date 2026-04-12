import io
import json
import logging
import os
from urllib.parse import urlparse

log = logging.getLogger(__name__)


# ── Fetchers (return raw bytes) ───────────────────────────────────────────────

def _fetch_s3(uri: str) -> bytes:
    import boto3
    parsed = urlparse(uri)
    bucket, key = parsed.netloc, parsed.path.lstrip("/")
    log.info(f"Fetching s3://{bucket}/{key}")
    obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    return obj["Body"].read()


def _fetch_gcs(uri: str) -> bytes:
    from google.cloud import storage
    parsed = urlparse(uri)
    bucket_name, blob_name = parsed.netloc, parsed.path.lstrip("/")
    log.info(f"Fetching gs://{bucket_name}/{blob_name}")
    client = storage.Client()
    return client.bucket(bucket_name).blob(blob_name).download_as_bytes()


def _fetch_local(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _fetch(ref: str) -> bytes:
    if ref.startswith("s3://"):
        return _fetch_s3(ref)
    if ref.startswith("gs://"):
        return _fetch_gcs(ref)
    return _fetch_local(ref)


# ── Parsers (bytes → plain text) ─────────────────────────────────────────────

def _parse_pdf(data: bytes) -> str:
    import PyPDF2
    reader = PyPDF2.PdfReader(io.BytesIO(data))
    return "\n".join(
        page.extract_text() or "" for page in reader.pages
    )


def _parse_docx(data: bytes) -> str:
    import docx
    doc = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


def _parse_xlsx(data: bytes) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    lines = []
    for sheet in wb.worksheets:
        lines.append(f"[Sheet: {sheet.title}]")
        for row in sheet.iter_rows(values_only=True):
            lines.append("\t".join("" if v is None else str(v) for v in row))
    return "\n".join(lines)


def _parse(name: str, data: bytes) -> str:
    ext = os.path.splitext(name)[1].lower()
    if ext == ".pdf":
        return _parse_pdf(data)
    if ext == ".docx":
        return _parse_docx(data)
    if ext == ".xlsx":
        return _parse_xlsx(data)
    return data.decode("utf-8", errors="replace")


# ── Public entry point ────────────────────────────────────────────────────────

def ingest(submission_path):
    with open(submission_path) as f:
        submission = json.load(f)

    docs = {}
    for ref in submission.get("document_refs", []):
        name = os.path.basename(ref)
        try:
            raw = _fetch(ref)
            docs[name] = _parse(name, raw)
        except FileNotFoundError:
            log.warning(f"Document not found, skipping: {ref}")
            docs[name] = ""
        except Exception as e:
            log.error(f"Failed to load {ref}: {e}")
            docs[name] = ""

    return submission, docs
