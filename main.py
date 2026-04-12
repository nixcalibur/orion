import json
import logging
import sys
from datetime import datetime, timezone

from ingest import ingest
from extract import extract_profile
from score import score_profile, get_authorization_level, generate_followup_questions
from schema import AssessmentResult
from audit import write_audit_record
from deliver import deliver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def run_pipeline(submission_path):
    log.info(f"Starting ORION pipeline for: {submission_path}")

    # 1. Ingest submission + documents
    submission, docs = ingest(submission_path)
    log.info(
        f"Loaded submission '{submission['submission_id']}' "
        f"with {len(docs)} document(s)"
    )

    # 2. Extract structured risk profile via Claude
    log.info("Extracting risk profile...")
    profile = extract_profile(submission, docs)
    if "error" in profile:
        log.error(f"Profile extraction failed: {profile['error']}")
        return None
    log.info(f"Profile: {json.dumps(profile)}")

    # 3. Score dimensions and compute composite
    dim_scores, composite = score_profile(profile)
    authorization = get_authorization_level(composite, profile)
    log.info(f"Composite score: {composite} → {authorization}")

    # 4. Generate follow-up questions
    questions = generate_followup_questions(profile, submission)

    # 5. Write audit record before building result
    write_audit_record(
        submission=submission,
        docs=docs,
        profile=profile,
        dim_scores=dim_scores,
        composite=composite,
        authorization=authorization,
        followup_questions=questions,
        model="gpt-4o-mini",
    )

    # 6. Build and validate reviewer-ready result
    result = AssessmentResult(
        submission_id=submission["submission_id"],
        applicant_name=submission.get("applicant_name"),
        assessed_at=datetime.now(timezone.utc),
        authorization_level=authorization,
        composite_score=composite,
        dimension_scores=dim_scores,
        risk_profile=profile,
        declared_activities=submission.get("declared_activities", []),
        activities_verified=profile.get("activities_verified", []),
        activities_undeclared=profile.get("activities_undeclared", []),
        followup_questions=questions,
        key_findings=profile.get("key_findings", []),
    )
    log.info("Output validated against schema")

    # 7. Deliver to external review API
    deliver(result.json())

    return result


if __name__ == "__main__":
    import os

    arg = sys.argv[1] if len(sys.argv) > 1 else None

    if arg is None:
        # No argument: run all dataset entries
        entries = sorted(os.listdir("dataset"))
        paths = [
            f"dataset/{e}/submission.json"
            for e in entries
            if os.path.exists(f"dataset/{e}/submission.json")
        ]
    elif os.path.exists(arg):
        # Full path passed directly
        paths = [arg]
    elif os.path.exists(f"dataset/{arg}/submission.json"):
        # Bare submission ID passed, e.g. fc3e4000
        paths = [f"dataset/{arg}/submission.json"]
    else:
        print(f"Error: cannot find submission '{arg}'")
        sys.exit(1)

    for path in paths:
        result = run_pipeline(path)
        if result:
            print(result.json(indent=2))
