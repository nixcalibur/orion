# ORION — System Design Document (one-page)

## 1. Objective

Build an AI-assisted compliance review system that ingests regulatory license
submissions (JSON metadata + supporting documents), extracts a structured risk
profile, and produces an **auditable, deterministic authorization
recommendation** — with a human always making the final decision.

## 2. Scope & boundaries

**In scope**
- Ingest: local/S3/GCS files; PDF/DOCX/XLSX/TXT parsing; JSON submissions and
  standalone documents.
- Extraction: majority-vote LLM extraction with source-cited evidence,
  prompt-injection isolation, fail-closed schema validation.
- Scoring: deterministic dimension scoring → `APPROVE | CONDITIONAL | DEFER |
  REJECT`, hard overrides, env-tunable thresholds.
- Outputs: audit log (JSONL), SQLite review store, durable job tracking,
  optional external delivery, thin FastAPI + optional React UI.
- Evaluation: labeled in-sample set (23) + held-out set (12), offline mock mode,
  CI guardrail.

**Out of scope (explicitly)**
- Not a certified/regulated production compliance system.
- No RBAC/SSO, no multi-tenant isolation, no horizontal scale-out.
- LLM is an extractor only — it never decides the outcome.

## 3. Users

| User | Need |
|---|---|
| Compliance officer | Review 50 submissions/month in minutes, not 4–6 h; consistent, evidence-backed decisions |
| Reviewer/approver | See *why* a recommendation was made; accept or override with a durable record |
| Regulator/auditor | Reproduce any decision from an immutable audit trail |

## 4. Functional requirements

- FR-1 Ingest a submission JSON + supporting docs, or a standalone document.
- FR-2 Extract a risk profile with per-dimension evidence citations.
- FR-3 Verify every evidence excerpt against its named source (drop, never invent).
- FR-4 Score dimensions deterministically and return a 0–10 composite.
- FR-5 Emit an append-only audit record (input hash, model, scores, delivery).
- FR-6 Persist latest assessment + reviewer decisions in SQLite.
- FR-7 Expose assessment/review endpoints over HTTP with optional API-key auth.
- FR-8 Evaluate classification accuracy against labeled and held-out packs.
- FR-9 Persist async job status and per-stage timing in SQLite so restart does not lose in-flight or error state.
- FR-10 Paginate and filter the assessment list (limit/offset + level/review status) for a growing queue.

## 5. Non-functional requirements

| NFR | Target |
|---|---|
| Offline demo | Entire pipeline runs with `ORION_LLM_PROVIDER=mock` — no API key |
| Per-run cost | Explicitly surfaced (votes × tokens); `ORION_EXTRACTION_VOTES=1` for smoke runs |
| Max upload | 50 MB/file (`ORION_MAX_UPLOAD_SIZE`), 413 on exceed |
| Security | Path traversal blocked; uploads sanitized; stale reviews invalidated by input hash |
| Testing | Unit + integration via pytest; CI on every push/PR; held-out floor 75% |
| Fail-closed | Invalid LLM output scores worst-case; extraction errors logged, never silent |

## 6. Acceptance criteria

- AC-1 100% of pytest suite passes in CI.
- AC-2 `evaluate.py --check-min-accuracy 0.75` passes on the mock provider.
- AC-3 100% in-sample classification accuracy on the calibrated set.
- AC-4 Held-out accuracy reported on ≥12 packs; treated as the generalization metric.
- AC-5 Every decision is reproducible from `audit.jsonl` (input hash + scores).
- AC-6 Review of a reassessed submission is flagged `STALE`, never silently reused.
- AC-7 A job submitted to the API is readable as `running`/`error`/`complete` after API restart from the SQLite job record.
- AC-8 `GET /assessments` supports limit/offset and filters without breaking existing consumers.

## 7. Roadmap / milestones

| Milestone | Status |
|---|---|
| M1 Core pipeline: ingest → extract → score → recommend → audit | Done |
| M2 Majority-vote extraction + evidence verification | Done |
| M3 Evaluation harness + calibration (23 in-sample) | Done |
| M4 SQLite store + FastAPI + review decisions | Done |
| M5 Security hardening (path traversal, stale reviews, upload limits) | Done |
| M6 Offline mock mode + held-out set (12) + CI guardrail | Done |
| M7 Bounded single-team pilot (defined below) | In progress |

### M7 — Bounded single-team pilot architecture

**Goal:** run ORION in one team, 1–5 reviewers, with real data, without rebuilding it into a SaaS.

| Layer | Pilot design | Still out of scope |
|---|---|---|
| **Deployment** | Single container on a VM or single Docker Compose host; API key per deployment | Kubernetes, multi-region, auto-scaling |
| **Identity** | One shared `ORION_API_KEY` for reviewers; no SSO/RBAC | Per-user roles, RBAC, multi-tenant isolation |
| **Data** | SQLite file on persistent disk + `audit.jsonl` backup; upload staging directory on same volume | Managed PostgreSQL, encrypted-at-rest beyond filesystem |
| **Concurrency** | Sequential background tasks per process; single API instance; 1–5 simultaneous reviewers | Load-balanced workers, message queue |
| **Upload lifecycle** | Files staged in `uploads/`; manual purge + backup per `docs/OPERATIONS.md` | Auto-expiry, object-store lifecycle policies |
| **Recovery** | Daily file-level backup of `orion.db`, `audit.jsonl`, and `uploads/`; restore by copying back | Point-in-time restore, automated failover |
| **Monitoring** | Disk space, job status SQL query, override rate SQL query | APM, alerting, log aggregation |
| **Scale ceiling** | 50–100 submissions/month on a single modest VM | 1,000+/month or sub-second SLA |

**Exit criteria for M7:**
1. 30-day real-data run with ≥80% reviewer audit completeness and ≤20% override rate.
2. No data loss across a planned restart (DB + uploads restored from backup).
3. `ORION_RUNNING_JOB_TIMEOUT_MINUTES` correctly surfaces stale jobs after a crash.
4. Held-out accuracy does not regress below the CI floor after any prompt change.

## 8. Key configuration surface

`OPENAI_API_KEY`, `ORION_LLM_PROVIDER`, `ORION_EXTRACTION_VOTES`,
`ORION_DOCS_DIR`, `ORION_UPLOAD_DIR`, `ORION_DB_PATH`, `ORION_API_KEY`,
`ORION_MAX_UPLOAD_SIZE`, `ORION_JOB_TTL_MINUTES`,
`ORION_RUNNING_JOB_TIMEOUT_MINUTES`,
`ORION_THRESHOLD_{REJECT,DEFER,CONDITIONAL}`, `REVIEW_API_URL`.
