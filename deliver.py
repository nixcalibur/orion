import logging
import os

import urllib.request
import urllib.error
import json

log = logging.getLogger(__name__)

REVIEW_API_URL = os.getenv("REVIEW_API_URL", "https://httpbin.org/post")


def deliver(result_json: str) -> dict:
    """POST the assessment result to the external review API."""
    url = REVIEW_API_URL
    data = result_json.encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            body = resp.read().decode("utf-8")
            log.info(f"Delivered to review API → {url} (HTTP {status})")
            return {"status": status, "response": json.loads(body)}
    except urllib.error.HTTPError as e:
        log.error(f"Review API returned HTTP {e.code}: {e.reason}")
        raise
    except urllib.error.URLError as e:
        log.error(f"Failed to reach review API at {url}: {e.reason}")
        raise
