# ORION — Operational Risk & Integrity Office

An AI-assisted compliance review system that reads regulatory submissions, extracts structured risk profiles, and produces auditable authorization recommendations — but a human is always the one who decides.

## The problem

A compliance officer reviews 50 license applications every month. Each submission includes JSON metadata and 3–12 supporting documents (PDF policies, Excel financials, DOCX organizational charts, scanned IDs). The review must cover ownership transparency, AML controls, regulatory history, cybersecurity posture, financial health, privacy compliance, and politically exposed person (PEP) screening. Every decision needs a documented rationale, because regulators ask "why?" months later.

Without tooling, this means:

- **4–6 hours per submission** reading documents and cross-referencing against checklists.
- **Inconsistent decisions** across reviewers. Same facts, different outcome.
- **No audit trail** connecting raw evidence to the final recommendation.

ORION cuts that to minutes and makes the reasoning explicit.

## What ORION does

1. **Ingests** a submission JSON + any attached documents (local files, S3, GCS).
2. **Parses** `.pdf`, `.docx`, `.xlsx`, and `.txt` into structured text.
3. **Extracts** a risk profile via LLM — ownership type, AML presence, regulatory history, cyber rating, financial health, privacy compliance, PEP status, criminal flags.
4. **Scores** each dimension with deterministic rules. No LLM decides the outcome.
5. **Recommends** `APPROVE`, `CONDITIONAL`, `DEFER`, or `REJECT`.
6. **Generates** follow-up questions for missing or inconsistent information.
7. **Writes** an append-only audit log (JSONL) with input hash, commit SHA, model fingerprint, prompt hash, and all scores.
8. **Delivers** the result to an external review API with retries and idempotency keys.

A human reviewer sees the recommendation, the evidence breakdown, and a complete reasoning trail — then accepts or overrides from a dashboard.

## Why this architecture

| Decision | Why |
|---|---|
| **LLM extracts, deterministic code decides** | The LLM reads documents and classifies facts. The scoring logic is pure Python — auditable, testable, version-controlled. If the model hallucinates an enum value, the system fails closed (worst-case score) and logs a warning. |
| **Input hashing** | Every run records `SHA-256(submission + docs)`. Same input, same hash. Makes it possible to answer "did we review this exact submission before?" |
| **Prompt isolation** | Document content is wrapped in `<document>` XML tags with explicit instructions to treat tag content as data, not commands. Mitigates prompt injection from adversarial documents. |
| **JSONL audit log** | Append-only. Each line is one run. Includes `commit_sha`, `model`, `system_fingerprint`, `prompt_hash`, and `extraction_params`. Enough to replay or debug any decision. |
| **Retry + idempotency** | LLM extraction retries on rate-limit/connection errors with exponential backoff. Delivery uses stable idempotency keys so duplicate POSTs are safe. |
| **Pydantic v2 schema** | Output contract validated before any result leaves the pipeline. `ReviewerOverride` cross-field validators enforce that overridden decisions include a reviewer ID and new level. |

### Risk dimensions scored

| Dimension | Values → Scores |
|---|---|
| Ownership | clear (0), complex (2), opaque (3) |
| AML policy present | true (0), false (3) |
| Regulatory history | clean (0), minor issues (1), major issues (3) |
| Cyber posture | strong/adequate (0), weak/inadequate (0.5) |
| Financial health | healthy (0), marginal (0.5), stressed (1), distressed (1) |
| Privacy compliance | compliant (0), partial (0.5), non-compliant (1) |
| Has PEP | false (0), true (1) |
| Has criminal flag | false (0), true (4) |
| Missing documents | +0.5 per doc |

Composite score = `(raw / max_raw) * 10`, clamped to 0–10.

Hard overrides: criminal flag or major regulatory history → `REJECT`, regardless of score.

## Evaluation

23 labeled submissions with ground-truth authorization levels:

| Level | Count |
|---|---|
| CONDITIONAL | 10 |
| DEFER | 8 |
| REJECT | 3 |
| APPROVE | 2 |

Run evaluation:

```bash
python evaluate.py
```

Compares predicted vs. expected authorization level for each submission. Ground truth files include `expected_composite_range` for sensitivity testing.

## Repository structure

**Pipeline** — each file does one thing

- `main.py` — end-to-end orchestration (run one, run all)
- `handler.py` — Lambda/Cloud Run entrypoint with timeout guard
- `ingest.py` — fetch from local, S3, or GCS; parse PDF/DOCX/XLSX/TXT; enforce per-document and total character budgets
- `extract.py` — LLM extraction with retry on rate-limit/connection errors; XML-delimited documents for prompt injection mitigation
- `score.py` — deterministic dimension scoring, composite normalization, authorization-level thresholds, follow-up question generator
- `schema.py` — Pydantic v2 models (`RiskProfile`, `AssessmentResult`, `ReviewerOverride`) with cross-field validators
- `audit.py` — append-only JSONL audit records with input hash, commit SHA, model fingerprint, prompt hash
- `deliver.py` — POST results to external review API with 4-retry exponential backoff and idempotency keys

**API & UI**

- `api.py` — FastAPI backend serving the dashboard and wrapping `run_pipeline()` for background submission processing
- `frontend/` — React 18 + Vite + Tailwind v4 + Recharts

**Other**

- `dataset/` — 23 sample submissions with ground truth labels
- `tests/` — 28 pytest tests covering all scoring paths, authorization levels, schema validators, and edge cases

## Quick start

```bash
# Install
pip install -r requirements.txt
cp .env.example .env   # add your OPENAI_API_KEY

# Run one submission
python main.py dataset/fc3e4000/submission.json

# Run all
python main.py

# Serverless entrypoint
python handler.py '{"submission_id":"fc3e4000"}'
```

## Dashboard

Run two terminals from the project root:

```bash
# Terminal 1 — API
uvicorn api:app --reload

# Terminal 2 — UI
cd frontend && npm install && npm run dev
```

Open `http://localhost:5173`.

| Route | Description |
|---|---|
| `/` | Stats cards, distribution donut, 7-day trend, recent submissions |
| `/submissions` | Searchable, filterable table of all assessments |
| `/submissions/:id` | Full detail: dimension scores chart, key findings, reviewer action panel |
| `/submit` | Drag-and-drop upload form with multi-file document attachments |

<img width="1465" height="803" alt="Dashboard" src="https://github.com/user-attachments/assets/f57dc88f-a29f-4eaa-8644-744123f924f9" />

<img width="1464" height="803" alt="Submissions" src="https://github.com/user-attachments/assets/28b0f4be-d208-4036-98da-d71d19ed4156" />

<img width="1465" height="804" alt="Detail" src="https://github.com/user-attachments/assets/4b77be9f-4e1b-44af-a09b-5f4a1f3a193b" />

## Tests

```bash
pytest tests/ -v   # 28 tests, all passing
```

Covers: `score_profile` (all four authorization paths, criminal-flag override, missing-doc penalty, composite clamping, fail-closed unknown values), `get_authorization_level` (threshold boundaries, hard-rule overrides), `ReviewerOverride` validators (ACCEPTED requires reviewer_id, OVERRIDDEN requires both reviewer_id and override_level), and `RiskProfile` enum rejection for all five categorical dimensions.

## Docker

```bash
docker build -t orion-pipeline .
docker run --rm -e OPENAI_API_KEY="$OPENAI_API_KEY" orion-pipeline python handler.py '{"submission_id":"fc3e4000"}'
```

## Audit log

Each pipeline run appends one JSON line to `audit.jsonl`:

```json
{
  "timestamp": "2026-07-29T09:44:48.619754+00:00",
  "status": "success",
  "submission_id": "05b74dcc",
  "input_hash": "959b9171c2b12cb1...",
  "commit_sha": "3092a3f",
  "model": "gpt-4o-mini-2024-07-18",
  "system_fingerprint": "fp_c881474fd1",
  "prompt_hash": "4664616476...",
  "extraction_params": {"temperature": 0, "seed": 42},
  "extracted_profile": { ... },
  "dimension_scores": { ... },
  "composite_score": 3.94,
  "authorization_level": "CONDITIONAL",
  "followup_questions": [ ... ]
}
```

Includes `status: "error"` records for extraction failures and schema validation rejections.
