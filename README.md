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

**Pipeline**
- `handler.py` — serverless-style entrypoint with timeout guard.
- `main.py` — end-to-end orchestration.
- `ingest.py` — fetch + parse + truncation budget for docs.
- `extract.py` — LLM extraction into strict JSON profile (retry on rate-limit/connection errors; document content isolated in XML delimiters to mitigate prompt injection).
- `score.py` — deterministic scoring + recommendation + follow-ups (max raw score derived programmatically from `DIMENSION_SCORES`).
- `schema.py` — Pydantic v2 output contracts and review override model.
- `audit.py` — append-only JSONL audit records (includes `status` field for error tracking).
- `deliver.py` — external API delivery with retries + idempotency key.

**API & UI**
- `api.py` — FastAPI HTTP layer wrapping the pipeline; serves the dashboard backend.
- `frontend/` — React 18 + Vite + Tailwind v4 dashboard (Dashboard, Submissions list, Detail view, Upload form).

**Other**
- `dataset/` — sample submissions and expected outcomes.
- `tests/` — pytest unit tests for scoring logic and schema validation.

---

## Requirements

- Python 3.11+
- Pydantic v2 (`pydantic>=2.0`)
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

## Running the UI

The dashboard is a FastAPI backend + React/Vite frontend. Run both concurrently from the project root.

**Backend**

```bash
pip install fastapi uvicorn python-multipart
uvicorn api:app --reload
```

The API runs at `http://localhost:8000`. It reads `audit.jsonl` and wraps `run_pipeline()` for background processing.

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

The UI runs at `http://localhost:5173`. All `/api` requests proxy automatically to the backend — no CORS configuration needed on the client.

---

## Preview

<img width="1465" height="803" alt="1" src="https://github.com/user-attachments/assets/f57dc88f-a29f-4eaa-8644-744123f924f9" />

<img width="1464" height="803" alt="2" src="https://github.com/user-attachments/assets/28b0f4be-d208-4036-98da-d71d19ed4156" />

<img width="1465" height="804" alt="3" src="https://github.com/user-attachments/assets/4b77be9f-4e1b-44af-a09b-5f4a1f3a193b" />

---

## Auditability and reproducibility

Each run appends one line to `audit.jsonl`, including:

- `status` (`"success"` or `"error"`)
- `input_hash` (SHA-256 of submission + docs)
- `commit_sha`
- resolved model + backend fingerprint
- `prompt_hash` and extraction params
- scores, recommendation, and follow-up questions

This supports review traceability and replay diagnostics.

---

## Tests

```bash
pytest tests/
```

Covers `score_profile` (APPROVE/CONDITIONAL/DEFER/REJECT paths, criminal flag override, missing-doc penalties, composite clamping), `get_authorization_level` (all four thresholds + both hard-rule overrides), `ReviewerOverride` validators, and `RiskProfile` enum rejection.

---

## Evaluation

Batch evaluation script:

```bash
python evaluate.py
```

This compares predicted authorization levels to `dataset/*/ground_truth.json`.

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

**Views**

| Route | Description |
|---|---|
| `/` | Dashboard — stats cards, donut chart, 7-day bar chart, recent submissions |
| `/submissions` | Searchable and filterable submissions table |
| `/submissions/:id` | Full assessment detail, dimension scores chart, reviewer action panel |
| `/submit` | Drag-and-drop upload form for new submissions |

---

## Notes

- If `OPENAI_API_KEY` is missing/invalid, extraction fails and the pipeline returns an error response.
- Delivery retries transient API errors with exponential backoff.
- Ingestion enforces per-document and total text budgets to fit serverless/runtime constraints.
