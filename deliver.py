import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid

log = logging.getLogger(__name__)

# Demo default keeps the CLI usable out of the box. Set REVIEW_API_URL="" to skip.
DEFAULT_REVIEW_API_URL = "https://httpbin.org/post"

# Retry config — tunable via env so the API/UI can fail fast while the serverless
# handler can keep a longer retry policy.
MAX_ATTEMPTS = int(os.getenv("ORION_DELIVERY_MAX_ATTEMPTS", "4"))
BACKOFF_BASE = float(os.getenv("ORION_DELIVERY_BACKOFF_BASE", "1.5"))  # seconds; delay = BACKOFF_BASE * 2^attempt
REQUEST_TIMEOUT = float(os.getenv("ORION_DELIVERY_TIMEOUT", "10"))

# HTTP status codes that are transient and worth retrying
RETRIABLE_STATUSES = {429, 500, 502, 503, 504}


class DeliveryError(Exception):
    """Raised when delivery fails after all retries or hits a non-retriable error."""
    def __init__(self, message: str, retriable: bool, status_code: int = None):
        super().__init__(message)
        self.retriable = retriable
        self.status_code = status_code


def _idempotency_key(submission_id: str, input_hash: str) -> str:
    """Stable key scoped to this exact submission + input content."""
    return f"{submission_id}-{input_hash[:16]}"


def deliver(result_json: str, submission_id: str = "", input_hash: str = "") -> dict:
    """
    POST the assessment result to the external review API.

    Returns an outcome dict: {"outcome": "success"|"skipped", "detail": ...}.
    Retries transient failures with exponential backoff.
    Raises DeliveryError on non-retriable failures or exhausted retries.
    """
    url = os.getenv("REVIEW_API_URL", DEFAULT_REVIEW_API_URL)
    if not url:
        log.info("REVIEW_API_URL not set — delivery skipped")
        return {"outcome": "skipped", "detail": "REVIEW_API_URL not set"}

    data = result_json.encode("utf-8")
    idem_key = _idempotency_key(submission_id, input_hash) if submission_id else str(uuid.uuid4())

    headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": idem_key,
    }

    last_error = None
    for attempt in range(MAX_ATTEMPTS):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                status = resp.status
                body = resp.read().decode("utf-8")
                log.info(
                    f"Delivered to review API | url={url} status={status} "
                    f"attempt={attempt+1} idempotency_key={idem_key}"
                )
                return {"outcome": "success", "detail": f"HTTP {status}", "status_code": status, "response": json.loads(body)}

        except urllib.error.HTTPError as e:
            retriable = e.code in RETRIABLE_STATUSES
            log.warning(
                f"Review API HTTP error | status={e.code} retriable={retriable} "
                f"attempt={attempt+1}/{MAX_ATTEMPTS} idempotency_key={idem_key}"
            )
            last_error = DeliveryError(
                f"HTTP {e.code}: {e.reason}", retriable=retriable, status_code=e.code
            )
            if not retriable:
                raise last_error

        except urllib.error.URLError as e:
            log.warning(
                f"Review API network error | reason={e.reason} "
                f"attempt={attempt+1}/{MAX_ATTEMPTS} idempotency_key={idem_key}"
            )
            last_error = DeliveryError(f"Network error: {e.reason}", retriable=True)

        if attempt < MAX_ATTEMPTS - 1:
            delay = BACKOFF_BASE * (2 ** attempt)
            log.info(f"Retrying delivery in {delay:.1f}s...")
            time.sleep(delay)

    raise DeliveryError(
        f"Delivery failed after {MAX_ATTEMPTS} attempts: {last_error}",
        retriable=False,
    )
