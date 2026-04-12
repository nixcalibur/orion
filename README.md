# ORION (Operational Risk & Integrity Office) Pipeline

A minimal, auditable pipeline for reviewing ORION authorization submissions and producing a structured risk recommendation for human reviewers.

## What this does

For each submission, the pipeline:

1. Ingests a primary JSON and referenced documents (local, `s3://`, `gs://`).
2. Parses supported document formats (`.txt`, `.pdf`, `.docx`, `.xlsx`).
3. Uses an LLM to extract a structured risk profile.
4. Applies deterministic scoring rules to compute a composite risk score.
5. Recommends an authorization level (`APPROVE`, `CONDITIONAL`, `DEFER`, `REJECT`).
6. Generates follow-up questions for missing/inconsistent information.
7. Validates output schema and writes an audit log.
8. Delivers result JSON to an external review API.

---

## Repository structure

- `handler.py` — serverless-style entrypoint with timeout guard.
- `main.py` — end-to-end orchestration.
- `ingest.py` — fetch + parse + truncation budget for docs.
- `extract.py` — LLM extraction into strict JSON profile.
- `score.py` — deterministic scoring + recommendation + follow-ups.
- `schema.py` — Pydantic output contracts and review override model.
- `audit.py` — append-only JSONL audit records.
- `deliver.py` — external API delivery with retries + idempotency key.
- `dataset/` — sample submissions and expected outcomes.

---

## Requirements

- Python 3.11+
- OpenAI API key

Install dependencies:

```bash
pip install -r requirements.txt
```

Set environment variables:

```bash
export OPENAI_API_KEY="<your-key>"
# Optional:
export REVIEW_API_URL="https://httpbin.org/post"
export PIPELINE_TIMEOUT_SECONDS="270"
```

---

## Run locally

Run one submission by ID:

```bash
python handler.py '{"submission_id":"fc3e4000"}'
```

Run one submission by path:

```bash
python main.py dataset/fc3e4000/submission.json
```

Run all dataset submissions:

```bash
python main.py
```

---

## Docker

Build:

```bash
docker build -t orion-pipeline .
```

Run:

```bash
docker run --rm \
  -e OPENAI_API_KEY="$OPENAI_API_KEY" \
  -e REVIEW_API_URL="https://httpbin.org/post" \
  orion-pipeline \
  python handler.py '{"submission_id":"fc3e4000"}'
```

---

## Input format

Each submission JSON should include:

- `submission_id`
- applicant metadata (`applicant_name`, `jurisdiction`, etc.)
- `declared_activities`
- `document_refs` (paths or object storage URIs)

Example (`document_refs` may include mixed formats):

```json
{
  "submission_id": "sample_formats",
  "document_refs": [
    "dataset/sample_formats/docs/aml_policy.pdf",
    "dataset/sample_formats/docs/ownership.docx",
    "dataset/sample_formats/docs/financials.xlsx"
  ]
}
```

---

## Output format

Validated `AssessmentResult` includes:

- risk dimension scores
- composite score
- authorization recommendation
- extracted risk profile
- follow-up questions
- reviewer status block (pending/accepted/overridden)

Response is returned by `handler.py` as:

```json
{ "statusCode": 200, "body": "<AssessmentResult JSON>" }
```

---

## Auditability and reproducibility

Each run appends one line to `audit.jsonl`, including:

- `input_hash` (SHA-256 of submission + docs)
- `commit_sha`
- resolved model + backend fingerprint
- `prompt_hash` and extraction params
- scores, recommendation, and follow-up questions

This supports review traceability and replay diagnostics.

---

## Evaluation

Batch evaluation script:

```bash
python evaluate.py
```

This compares predicted authorization levels to `dataset/*/ground_truth.json`.

---

## Notes

- If `OPENAI_API_KEY` is missing/invalid, extraction fails and the pipeline returns an error response.
- Delivery retries transient API errors with exponential backoff.
- Ingestion enforces per-document and total text budgets to fit serverless/runtime constraints.
