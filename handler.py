"""
Lambda-compatible serverless entrypoint for the ORION pipeline.

Event schema:
  { "submission_path": "s3://bucket/path/submission.json" }
  { "submission_id": "fc3e4000" }   # shorthand for local dataset

Environment:
  PIPELINE_TIMEOUT_SECONDS  max wall-clock seconds before abort (default: 270)
"""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from main import run_pipeline

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

TIMEOUT = int(os.getenv("PIPELINE_TIMEOUT_SECONDS", "270"))


def _resolve_path(event: dict) -> str:
    if "submission_path" in event:
        return event["submission_path"]
    if "submission_id" in event:
        sid = event["submission_id"]
        path = f"dataset/{sid}/submission.json"
        if not os.path.exists(path):
            raise FileNotFoundError(f"No local submission found for id '{sid}'")
        return path
    raise ValueError("Event must contain 'submission_path' or 'submission_id'")


def lambda_handler(event: dict, context=None) -> dict:
    """
    AWS Lambda / Cloud Run compatible handler.
    Returns a dict with statusCode and body (JSON string).
    """
    log.info(f"Handler invoked. timeout={TIMEOUT}s event={json.dumps(event)}")

    try:
        submission_path = _resolve_path(event)
    except (ValueError, FileNotFoundError) as e:
        log.error(str(e))
        return {"statusCode": 400, "body": json.dumps({"error": str(e)})}

    # Honour remaining Lambda time if context provides it
    effective_timeout = TIMEOUT
    if context and hasattr(context, "get_remaining_time_in_millis"):
        remaining = context.get_remaining_time_in_millis() / 1000
        # Leave a 5-second buffer for delivery and cleanup
        effective_timeout = min(TIMEOUT, remaining - 5)
        log.info(f"Lambda remaining time: {remaining:.0f}s → using timeout {effective_timeout:.0f}s")

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_pipeline, submission_path)
        try:
            result = future.result(timeout=effective_timeout)
        except FuturesTimeout:
            msg = f"Pipeline exceeded execution limit ({effective_timeout}s)"
            log.error(msg)
            return {"statusCode": 504, "body": json.dumps({"error": msg})}
        except Exception as e:
            log.exception("Pipeline failed with unhandled exception")
            return {"statusCode": 500, "body": json.dumps({"error": str(e)})}

    if result is None:
        return {"statusCode": 422, "body": json.dumps({"error": "Pipeline returned no result"})}

    return {"statusCode": 200, "body": result.model_dump_json()}


if __name__ == "__main__":
    import sys

    raw = sys.argv[1] if len(sys.argv) > 1 else None
    if raw is None:
        print("Usage: python handler.py '{\"submission_id\": \"fc3e4000\"}'")
        sys.exit(1)

    response = lambda_handler(json.loads(raw))
    print(json.dumps(response, indent=2))
