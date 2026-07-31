import hashlib
import io
import json
import logging
import os
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# Per-document character cap (~15k tokens). Truncated docs get a notice appended.
DOC_CHAR_LIMIT = 12_000
# Total docs_text cap passed to the LLM (~60k tokens).
TOTAL_CHAR_LIMIT = 48_000


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


# Local file reads are confined to this base (project root by default). Set
# ORION_DOCS_DIR to narrow it. Prevents path traversal via user-supplied refs.
ALLOWED_DOC_BASE = os.path.realpath(os.getenv("ORION_DOCS_DIR", os.getcwd()))


def _resolve_ref(ref: str) -> str:
    """Resolve a ref to an absolute path, blocking escapes outside the allowed base."""
    if ref.startswith("s3://") or ref.startswith("gs://"):
        return ref
    resolved = ref if os.path.isabs(ref) else os.path.join(os.getcwd(), ref)
    resolved = os.path.realpath(resolved)
    try:
        if os.path.commonpath([resolved, ALLOWED_DOC_BASE]) != ALLOWED_DOC_BASE:
            raise ValueError(f"Path outside allowed docs directory: {ref}")
    except ValueError:
        raise ValueError(f"Path outside allowed docs directory: {ref}")
    return resolved


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
    return "\n".join(page.extract_text() or "" for page in reader.pages)


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


def _truncate(name: str, text: str) -> str:
    """Truncate a single document to DOC_CHAR_LIMIT with a clear notice."""
    if len(text) <= DOC_CHAR_LIMIT:
        return text
    kept = text[:DOC_CHAR_LIMIT]
    dropped = len(text) - DOC_CHAR_LIMIT
    log.warning(f"{name}: truncated {dropped} chars (>{DOC_CHAR_LIMIT} char limit)")
    return kept + f"\n\n[TRUNCATED: {dropped} additional characters omitted]"


def _apply_total_budget(docs: dict) -> tuple:
    """
    If the combined text across all docs exceeds TOTAL_CHAR_LIMIT,
    trim the longest documents first until the total fits.
    Returns (docs, trimmed) so callers can flag that evidence may be incomplete.
    """
    total = sum(len(v) for v in docs.values())
    if total <= TOTAL_CHAR_LIMIT:
        return docs, False

    log.warning(
        f"Total doc size {total} chars exceeds budget {TOTAL_CHAR_LIMIT}; trimming."
    )
    result = dict(docs)
    while sum(len(v) for v in result.values()) > TOTAL_CHAR_LIMIT:
        longest = max(result, key=lambda k: len(result[k]))
        current = result[longest]
        trim_to = max(len(current) // 2, 500)
        dropped = len(current) - trim_to
        result[longest] = (
            current[:trim_to]
            + f"\n\n[TRUNCATED: {dropped} additional characters omitted]"
        )
    return result, True


# ── Public entry point ────────────────────────────────────────────────────────

def ingest(submission_path):
    try:
        with open(submission_path) as f:
            submission = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Not JSON — treat as a standalone document submission
        name = os.path.basename(submission_path)
        sid = hashlib.sha256(submission_path.encode()).hexdigest()[:8]
        log.info(f"Non-JSON input: treating '{name}' as a standalone document (submission_id={sid})")
        submission = {
            "submission_id": sid,
            "applicant_name": None,
            "jurisdiction": None,
            "declared_activities": [],
            "document_refs": [submission_path],
        }

    docs = {}
    truncated_docs = []
    for ref in submission.get("document_refs", []):
        try:
            resolved = _resolve_ref(ref)
            name = os.path.basename(resolved)
            raw = _fetch(resolved)
            text = _parse(name, raw)
            if len(text) > DOC_CHAR_LIMIT:
                truncated_docs.append(name)
            docs[name] = _truncate(name, text)
        except FileNotFoundError:
            log.warning(f"Document not found, skipping: {resolved}")
            docs[os.path.basename(ref)] = "[MISSING: document could not be located]"
        except ValueError as e:
            log.error(f"Document ref rejected: {e}")
            docs[os.path.basename(ref)] = "[BLOCKED: path outside allowed docs directory]"
        except Exception as e:
            log.error(f"Failed to load {resolved}: {e}")
            docs[os.path.basename(ref)] = ""

    docs, budget_trimmed = _apply_total_budget(docs)
    meta = {"truncated_docs": truncated_docs, "total_budget_trimmed": budget_trimmed}
    return submission, docs, meta
