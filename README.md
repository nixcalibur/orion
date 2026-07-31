# ORION — Operational Risk & Integrity Office

An AI-assisted compliance review system that reads regulatory submissions, extracts structured risk profiles, and produces auditable authorization recommendations — but a human is always the one who decides.

> **Demo / research prototype:** ORION is built for local walkthroughs and evaluation. It is not a certified production compliance system.

## For reviewers

You do not need the command line. The reviewer UI lets you try a sample submission, upload your own files, watch the assessment run, and accept or override the recommendation.

### Option 1: Docker (one command)

```bash
# Copy .env.example to .env and add OPENAI_API_KEY first.
docker-compose up --build
```

Then open http://localhost:5173 and click **Try a sample submission**.

### Option 2: two terminals

```bash
# Terminal 1: API server
pip install -r requirements.txt
uvicorn api:app --reload

# Terminal 2: UI
npm install --prefix ui
npm run dev --prefix ui
```

Open http://localhost:5173 and click **Try a sample submission**.

### What to upload

The quickest way to see ORION is to click **Try a sample submission** on the Upload tab.

You can also upload your own files:
- A `submission.json` plus its supporting documents (PDF, DOCX, XLSX, TXT), **or**
- A single standalone document (PDF/DOCX/XLSX/TXT).

The pipeline runs in the background. Once complete, the **Detail** tab shows the recommendation, why it was made, evidence excerpts, follow-up questions, and the Accept/Override controls. Decisions are recorded in the assessment list.

## The problem

A compliance officer reviews 50 license applications every month. Each submission includes JSON metadata and 3–12 supporting documents (PDF policies, Excel financials, DOCX organizational charts, scanned IDs). The review must cover ownership transparency, AML controls, regulatory history, cybersecurity posture, financial health, privacy compliance, and politically exposed person (PEP) screening. Every decision needs a documented rationale, because regulators ask "why?" months later.

Without tooling, this means:

- **4–6 hours per submission** reading documents and cross-referencing against checklists.
- **Inconsistent decisions** across reviewers. Same facts, different outcome.
- **No audit trail** connecting raw evidence to the final recommendation.

ORION cuts that to minutes and makes the reasoning explicit.

## What ORION does

1. **Ingests** a submission JSON + any attached documents (local files, S3, GCS), or a standalone document file directly.
2. **Parses** `.pdf`, `.docx`, `.xlsx`, and `.txt` into structured text.
3. **Extracts** a risk profile via LLM — ownership type, AML presence, regulatory history, cyber rating, financial health, privacy compliance, PEP status, criminal flags — with source citations per dimension.
4. **Scores** each dimension with deterministic rules. No LLM decides the outcome.
5. **Recommends** `APPROVE`, `CONDITIONAL`, `DEFER`, or `REJECT`.
6. **Generates** follow-up questions for missing or inconsistent information.
7. **Writes** an append-only audit log (JSONL) with input hash, commit SHA, model fingerprint, prompt hash, and all scores.
8. **Delivers** the structured result to an external review API with retries and idempotency keys.

## Why this architecture

| Decision | Why |
|---|---|
| **LLM extracts, deterministic code decides** | The LLM reads documents and classifies facts. The scoring logic is pure Python — auditable, testable, version-controlled. If the model hallucinates an enum value, the system fails closed (worst-case score) and logs a warning. |
| **Input hashing** | Every run records `SHA-256(submission + docs)`. Same input, same hash. Makes it possible to answer "did we review this exact submission before?" |
| **Prompt isolation** | Document content is wrapped in `<document>` XML tags with explicit instructions to treat tag content as data, not commands. Mitigates prompt injection from adversarial documents. |
| **JSONL audit log** | Append-only. Each line is one run. Includes `commit_sha`, `model`, `system_fingerprint`, `prompt_hash`, and `extraction_params`. Enough to replay or debug any decision. |
| **Retry + idempotency** | LLM extraction retries on rate-limit/connection errors with exponential backoff. Delivery uses stable idempotency keys so duplicate POSTs are safe. |
| **Majority-vote extraction** | LLMs are nondeterministic even at temperature 0 — single-run accuracy swung ±13 points between identical runs. Extraction runs N passes (default 3, `ORION_EXTRACTION_VOTES`) with a distinct seed per pass (`SEED+i`, temperature stays 0) so votes are independent draws. Scalar fields vote (ties fail closed); list fields come from the run closest to the merged result. Set `ORION_EXTRACTION_VOTES=1` for cheap local runs at the cost of stability. |
| **Evidence verification** | Every evidence excerpt is checked against the ingested document text (case/whitespace-insensitive substring). Citations that don't match their named source are dropped with a warning — never replaced with invented ones. |
| **Explicit delivery status** | Every result and audit record carries `delivery: {status: success|failed|skipped, detail}`. Set `REVIEW_API_URL=""` to skip delivery; the default httpbin URL keeps the CLI demoable. Delivery failures are recorded, never silently swallowed. |
| **Ingestion honesty** | The audit record carries `ingest: {truncated_docs, total_budget_trimmed}` so a reviewer can see when evidence may be incomplete. Char budgets unchanged (12k/doc, 48k total). |
| **Durable review store** | Latest assessment per submission is dual-written to SQLite (`ORION_DB_PATH`, default `data/orion.db`) alongside `audit.jsonl`. Reviewer accepts/overrides persist via a thin FastAPI surface (`api.py`): `GET /health`, `GET /assessments`, `POST /assessments`, `GET /assessments/{id}`, `POST /assessments/{id}/review`. `POST /assessments` accepts a local path or uploaded files and starts an async pipeline run; the UI polls until it completes. Set `ORION_API_KEY` to require `Authorization: Bearer <key>` or `X-API-Key` on assessment routes; unset keeps open local access. `/health` stays open. |
| **Pydantic v2 schema** | Output contract validated before any result leaves the pipeline. `ReviewerOverride` cross-field validators enforce that overridden decisions include a reviewer ID and new level. |
| **Evidence attribution** | Each risk dimension classification includes a source document name and verbatim excerpt justifying it. Stored in the audit log, part of the pipeline output. |
| **Standalone document mode** | No JSON wrapper required. Point the pipeline at any `.pdf`, `.docx`, `.xlsx`, or `.txt` and it auto-wraps it into a submission. |

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
| Missing documents | +0.5 per doc, capped at 5 |

Composite score = `(raw / max_raw) * 10`, clamped to 0–10.

Hard overrides: criminal flag or major regulatory history → `REJECT`, regardless of score.

Normalization-base rule: a dimension is excluded from `max_raw` only when none of its values participate in a scored decision. `has_criminal_flag` qualifies (False scores 0, True hard-rejects before the composite is used), so its 4 points stay out of the base. `regulatory_history` stays in because `minor_issues` scores normally without triggering the override. The missing-docs penalty is capped so an unbounded LLM list can't dominate the score.

Authorization thresholds (`REJECT` ≥ 9.0, `DEFER` ≥ 4.5, `CONDITIONAL` ≥ 2.0) are tunable via `ORION_THRESHOLD_REJECT`, `ORION_THRESHOLD_DEFER`, `ORION_THRESHOLD_CONDITIONAL` env vars.

## Evaluation

23 labeled in-sample submissions with ground-truth authorization levels (used to calibrate the extraction rubric):

| Level | Count |
|---|---|
| CONDITIONAL | 10 |
| DEFER | 8 |
| REJECT | 3 |
| APPROVE | 2 |

Plus 2 synthetic **held-out** packs (`dataset/held_out_pep`, `dataset/held_out_major`) listed in `dataset/held_out.json`. These exercise PEP-missing-EDD and major-regulatory rules with fresh wording and were **not** used to tune prompt phrasing.

Run evaluation:

```bash
python evaluate.py
```

Compares predicted vs. expected authorization level per submission, then prints overall accuracy, in-sample vs held-out accuracy (when the manifest is present), per-class accuracy, a misclassification breakdown, and how often the composite score lands inside the ground-truth `expected_composite_range`.

### Measured results (gpt-4o-mini, majority vote ×3)

```
Accuracy: 23/23 (100%)   # in-sample labeled set — calibrated to these labels
Per-class: APPROVE 2/2, CONDITIONAL 10/10, DEFER 8/8, REJECT 3/3
Composite within expected range: 9/20
```

**This is not “solved.”** 100% on the in-sample set means the prompt rubric was calibrated to these 23 labels. Treat held-out accuracy from `evaluate.py` as the more honest generalization check; re-run after any prompt edit. Use `ORION_EXTRACTION_VOTES=1` for cheap smoke runs.

Getting here required encoding the review rubric explicitly in the prompt. The three calibration rules that mattered:

1. **Claimed vs. attached evidence** — a document stating evidence is "on record" is not the evidence; if the actual file isn't in the submission, it's missing.
2. **PEP conditional rule** — if `has_pep` is true and no dedicated EDD document is attached, it MUST appear in `missing_docs` (a policy section mentioning PEP handling doesn't count).
3. **Regulatory severity** — `major_issues` = sanctions/enforcement/suspension/ongoing investigations; `minor_issues` = administrative penalties fully remediated and closed. When in doubt, choose major.

Composite scores land inside the labelers' expected ranges less often (9/20) — the ranges reflect human severity intuition, while composites follow the deterministic formula. Classification decisions are what the system is scored on; do not retune dimension weights just to chase range hits.

## Repository structure

**Pipeline** — each file does one thing

- `main.py` — end-to-end orchestration (run one, run all)
- `handler.py` — Lambda/Cloud Run entrypoint with timeout guard
- `ingest.py` — fetch from local, S3, or GCS; parse PDF/DOCX/XLSX/TXT; auto-wrap standalone documents; enforce per-document and total character budgets
- `extract.py` — majority-vote LLM extraction (N passes, per-field vote, fail-closed ties); retry on rate-limit/connection errors; XML-delimited documents for prompt injection mitigation; per-dimension evidence citations
- `score.py` — deterministic dimension scoring, composite normalization, env-configurable authorization thresholds, follow-up question generator
- `schema.py` — Pydantic v2 models (`RiskProfile`, `Evidence`, `AssessmentResult`, `ReviewerOverride`) with cross-field validators
- `audit.py` — append-only JSONL audit records with input hash, commit SHA, model fingerprint, prompt hash, delivery outcome, ingest flags
- `deliver.py` — POST results to external review API with 4-retry exponential backoff and idempotency keys; explicit success/failed/skipped outcomes
- `db.py` — thin SQLite layer: latest assessment per submission + persisted reviewer decisions
- `api.py` — minimal FastAPI surface over the store (`GET /health`, `GET /assessments`, `POST /assessments`, `GET /assessments/{id}`, `POST /assessments/{id}/review`)
- `ui/` — minimal Vite + React reviewer UI (upload, queue, assessment detail, accept/override)
- `docker-compose.yml` — one-command local API + UI
- `evaluate.py` — batch evaluation harness with accuracy report and confusion breakdown

**Other**

- `dataset/` — 23 in-sample labeled submissions + 2 held-out packs (`held_out.json` manifest)
- `tests/` — pytest covering scoring paths, authorization levels, schema validators, evidence attribution + verification (incl. path basename matching), vote/merge logic, delivery outcomes, ingest flags, SQLite store, optional API auth, and verify-before-validate order
- `.github/workflows/ci.yml` — GitHub Actions: runs the test suite on every push and PR

## Quick start

```bash
# Install
pip install -r requirements.txt
cp .env.example .env   # then add your OPENAI_API_KEY

# Run one submission (JSON)
python main.py dataset/fc3e4000/submission.json

# Run one document directly (PDF/DOCX/XLSX/TXT — no JSON needed)
python main.py path/to/document.pdf

# Run all dataset submissions
python main.py

# Serverless entrypoint
python handler.py '{"submission_id":"fc3e4000"}'

# HTTP surface for assessments + reviews
# Set ORION_API_KEY in .env to require Bearer / X-API-Key on assessment routes
uvicorn api:app --reload
```

### Reviewer UI

```bash
npm install --prefix ui
npm run dev --prefix ui
# UI runs on http://localhost:5173 and proxies /api to the ORION backend.
```

The UI is a minimal Vite + React single-page app. Configure the API URL and optional key via environment variables:

```bash
VITE_API_URL=http://localhost:8000  # default /api in dev, proxied by Vite
VITE_API_KEY=your-secret            # only if ORION_API_KEY is set
```

## Tests

```bash
pytest tests/ -v
```

Runs in CI on every push via GitHub Actions.

Covers: `score_profile` (all four authorization paths, criminal-flag override, missing-doc penalty, composite clamping, fail-closed unknown values), `get_authorization_level` (threshold boundaries, hard-rule overrides), `ReviewerOverride` validators (ACCEPTED requires reviewer_id, OVERRIDDEN requires both reviewer_id and override_level), `RiskProfile` enum rejection for all five categorical dimensions, `Evidence` citation parsing + verification (basename / ambiguous source matching), optional API key auth, and pipeline order (verify evidence before `RiskProfile` validation).

## Docker

### Full reviewer stack (API + UI)

```bash
docker-compose up --build
```

API: http://localhost:8000  
UI: http://localhost:5173

### Pipeline container only

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
  "extraction_params": {"temperature": 0, "seeds": [42, 43, 44], "votes": 3},
  "extracted_profile": { "evidence": { "ownership": { "source_document": "...", "excerpt": "..." } } },
  "dimension_scores": { ... },
  "composite_score": 3.94,
  "authorization_level": "CONDITIONAL",
  "followup_questions": [ ... ],
  "delivery": {"status": "success", "detail": "HTTP 200"},
  "ingest": {"truncated_docs": ["terms_and_conditions.txt"], "total_budget_trimmed": false}
}
```

Includes `status: "error"` records for extraction failures and schema validation rejections.
