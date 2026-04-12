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


def _resolve_ref(ref: str) -> str:
    """Resolve a ref to an absolute path when it is relative (from CWD / project root)."""
    if ref.startswith("s3://") or ref.startswith("gs://"):
        return ref
    if not os.path.isabs(ref):
        return os.path.join(os.getcwd(), ref)
    return ref


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


def _apply_total_budget(docs: dict) -> dict:
    """
    If the combined text across all docs exceeds TOTAL_CHAR_LIMIT,
    trim the longest documents first until the total fits.
    """
    total = sum(len(v) for v in docs.values())
    if total <= TOTAL_CHAR_LIMIT:
        return docs

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
    return result


# ── Public entry point ────────────────────────────────────────────────────────

def ingest(submission_path):
    with open(submission_path) as f:
        submission = json.load(f)

    docs = {}
    for ref in submission.get("document_refs", []):
        resolved = _resolve_ref(ref)
        name = os.path.basename(resolved)
        try:
            raw = _fetch(resolved)
            text = _parse(name, raw)
            docs[name] = _truncate(name, text)
        except FileNotFoundError:
            log.warning(f"Document not found, skipping: {resolved}")
            docs[name] = "[MISSING: document could not be located]"
        except Exception as e:
            log.error(f"Failed to load {resolved}: {e}")
            docs[name] = ""

    docs = _apply_total_budget(docs)
    return submission, docs
