import json
import logging
import sys
from datetime import datetime, timezone

from pydantic import ValidationError

from ingest import ingest
from extract import extract_profile, verify_evidence
from score import score_profile, get_authorization_level, generate_followup_questions
from schema import AssessmentResult, DeliveryInfo, DeliveryStatus, ReviewerOverride, ReviewStatus, RiskProfile
from audit import write_audit_record, _hash_inputs
from db import store_assessment
from deliver import deliver, DeliveryError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def run_pipeline(submission_path, on_stage=None):
    """Run the ORION assessment pipeline.

    Args:
        submission_path: Path to a submission JSON or standalone document.
        on_stage: Optional callback(stage_name) invoked at coarse pipeline stages
                  (starting, ingest, extract, score, deliver, complete/error).
                  Useful for progress UI without changing pipeline logic.
    """
    def _stage(name):
        if on_stage:
            try:
                on_stage(name)
            except Exception:
                pass

    _stage("starting")
    log.info(f"Starting ORION pipeline for: {submission_path}")

    # 1. Ingest submission + documents
    _stage("ingest")
    submission, docs, ingest_meta = ingest(submission_path)
    log.info(
        f"Loaded submission '{submission['submission_id']}' "
        f"with {len(docs)} document(s)"
    )

    # 2. Extract structured risk profile
    _stage("extract")
    log.info("Extracting risk profile...")
    profile = extract_profile(submission, docs)
    if "error" in profile:
        log.error(f"Profile extraction failed: {profile['error']}")
        write_audit_record(
            submission=submission,
            docs=docs,
            profile={},
            dim_scores={},
            composite=0.0,
            authorization="",
            followup_questions=[],
            model="unknown",
            status="error",
            ingest_meta=ingest_meta,
        )
        _stage("error")
        return None
    log.info(f"Profile: {json.dumps(profile)}")

    # 2b. Verify evidence citations against ingested document text
    #    BEFORE RiskProfile validation — never validate/score unverified excerpts.
    profile = verify_evidence(profile, docs)

    # 3. Validate verified profile against schema BEFORE scoring (fail closed on bad LLM output).
    #    Pydantic ignores the extra "_"-prefixed metadata keys at this stage.
    try:
        risk_profile = RiskProfile(**profile)
    except ValidationError as e:
        log.error(f"RiskProfile validation failed: {e}")
        write_audit_record(
            submission=submission,
            docs=docs,
            profile=profile,
            dim_scores={},
            composite=0.0,
            authorization="",
            followup_questions=[],
            model=profile.get("_model", "unknown"),
            system_fingerprint=profile.get("_fp"),
            status="error",
            ingest_meta=ingest_meta,
        )
        _stage("error")
        return None

    # 4. Score dimensions and compute composite
    _stage("score")
    dim_scores, composite = score_profile(profile)
    authorization = get_authorization_level(composite, profile)
    log.info(f"Composite score: {composite} → {authorization}")

    # 5. Generate follow-up questions
    questions = generate_followup_questions(profile, submission)

    # 6. Pull LLM metadata out of the profile (profile is clean for the result)
    model = profile.pop("_model", "unknown")
    system_fingerprint = profile.pop("_fp", None)
    prompt_hash = profile.pop("_prompt_hash", None)
    extraction_params = profile.pop("_extraction_params", None)

    # 7. Build reviewer-ready result
    result = AssessmentResult(
        submission_id=submission["submission_id"],
        applicant_name=submission.get("applicant_name"),
        assessed_at=datetime.now(timezone.utc),
        authorization_level=authorization,
        composite_score=composite,
        dimension_scores=dim_scores,
        risk_profile=risk_profile,
        declared_activities=submission.get("declared_activities", []),
        activities_verified=profile.get("activities_verified", []),
        activities_undeclared=profile.get("activities_undeclared", []),
        followup_questions=questions,
        key_findings=profile.get("key_findings", []),
        review=ReviewerOverride(status=ReviewStatus.PENDING),
        ingest=ingest_meta,
    )
    log.info("Output validated against schema")

    # 8. Deliver to external review API — outcome is explicit, never assumed
    _stage("deliver")
    input_hash = _hash_inputs(submission, docs)
    try:
        outcome = deliver(result.model_dump_json(), submission_id=submission["submission_id"], input_hash=input_hash)
        status = DeliveryStatus.SUCCESS if outcome["outcome"] == "success" else DeliveryStatus.SKIPPED
        result.delivery = DeliveryInfo(status=status, detail=outcome.get("detail"))
    except DeliveryError as e:
        log.error(f"Delivery failed | retriable={e.retriable} status={e.status_code} error={e}")
        result.delivery = DeliveryInfo(status=DeliveryStatus.FAILED, detail=str(e))

    # 9. Write audit record (includes delivery outcome)
    write_audit_record(
        submission=submission,
        docs=docs,
        profile=profile,
        dim_scores=dim_scores,
        composite=composite,
        authorization=authorization,
        followup_questions=questions,
        model=model,
        system_fingerprint=system_fingerprint,
        prompt_hash=prompt_hash,
        extraction_params=extraction_params,
        delivery=result.delivery.model_dump(),
        ingest_meta=ingest_meta,
    )

    # 10. Persist latest assessment (dual-write with audit.jsonl; never fatal)
    _stage("complete")
    store_assessment(
        submission["submission_id"],
        result.assessed_at.isoformat(),
        result.model_dump_json(),
    )

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
            print(result.model_dump_json(indent=2))
