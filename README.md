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
| **Majority-vote extraction** | LLMs are nondeterministic even at temperature 0 — single-run accuracy swung ±13 points between identical runs. Extraction now runs N passes (default 3, `ORION_EXTRACTION_VOTES`), votes per scalar field (ties fail closed), and takes list fields from the run closest to the merged result. Run-to-run accuracy is now stable. |
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
| Missing documents | +0.5 per doc |

Composite score = `(raw / max_raw) * 10`, clamped to 0–10.

Hard overrides: criminal flag or major regulatory history → `REJECT`, regardless of score.

Authorization thresholds (`REJECT` ≥ 9.0, `DEFER` ≥ 4.5, `CONDITIONAL` ≥ 2.0) are tunable via `ORION_THRESHOLD_REJECT`, `ORION_THRESHOLD_DEFER`, `ORION_THRESHOLD_CONDITIONAL` env vars.

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

Compares predicted vs. expected authorization level per submission, then prints overall accuracy, per-class accuracy, a misclassification breakdown, and how often the composite score lands inside the ground-truth `expected_composite_range`.

### Measured results (gpt-4o-mini, majority vote ×3)

```
Accuracy: 14/23 (61%)  — stable across repeated runs
Per-class: APPROVE 2/2, CONDITIONAL 4/10, DEFER 7/8, REJECT 2/3
Composite within expected range: 11/20
```

Residual failures are systematic rubric disagreements, not variance: the model consistently judges PEP handling described inside an AML policy as sufficient (ground truth demands a dedicated EDD document), and rates some regulatory histories `minor_issues` where labels say `major_issues`. Closing that gap means encoding the labelers' exact rubric in the prompt — calibration work, not a bug.

## Repository structure

**Pipeline** — each file does one thing

- `main.py` — end-to-end orchestration (run one, run all)
- `handler.py` — Lambda/Cloud Run entrypoint with timeout guard
- `ingest.py` — fetch from local, S3, or GCS; parse PDF/DOCX/XLSX/TXT; auto-wrap standalone documents; enforce per-document and total character budgets
- `extract.py` — majority-vote LLM extraction (N passes, per-field vote, fail-closed ties); retry on rate-limit/connection errors; XML-delimited documents for prompt injection mitigation; per-dimension evidence citations
- `score.py` — deterministic dimension scoring, composite normalization, env-configurable authorization thresholds, follow-up question generator
- `schema.py` — Pydantic v2 models (`RiskProfile`, `Evidence`, `AssessmentResult`, `ReviewerOverride`) with cross-field validators
- `audit.py` — append-only JSONL audit records with input hash, commit SHA, model fingerprint, prompt hash
- `deliver.py` — POST results to external review API with 4-retry exponential backoff and idempotency keys
- `evaluate.py` — batch evaluation harness with accuracy report and confusion breakdown

**Other**

- `dataset/` — 23 sample submissions with ground truth labels
- `tests/` — 36 pytest tests covering all scoring paths, authorization levels, schema validators, edge cases, evidence attribution, and vote/merge logic
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
```

## Tests

```bash
pytest tests/ -v   # 36 tests, all passing
```

Runs in CI on every push via GitHub Actions.

Covers: `score_profile` (all four authorization paths, criminal-flag override, missing-doc penalty, composite clamping, fail-closed unknown values), `get_authorization_level` (threshold boundaries, hard-rule overrides), `ReviewerOverride` validators (ACCEPTED requires reviewer_id, OVERRIDDEN requires both reviewer_id and override_level), `RiskProfile` enum rejection for all five categorical dimensions, and `Evidence` citation parsing.

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
  "extracted_profile": { "evidence": { "ownership": { "source_document": "...", "excerpt": "..." } } },
  "dimension_scores": { ... },
  "composite_score": 3.94,
  "authorization_level": "CONDITIONAL",
  "followup_questions": [ ... ]
}
```

Includes `status: "error"` records for extraction failures and schema validation rejections.
