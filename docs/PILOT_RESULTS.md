# ORION — Mini-pilot results

A reproducible, synthetic-data pilot run on the 12 held-out packs in `dataset/held_out.json`. These packs were not used to tune prompt wording.

## Reproduce

```bash
# Real LLM (gpt-4o-mini, majority vote ×3) — costs a few cents
python evaluate.py --held-out-only

# Deterministic mock (no API calls, no cost)
ORION_LLM_PROVIDER=mock ORION_EXTRACTION_VOTES=1 python evaluate.py --held-out-only

# Time a single real-LLM end-to-end submission
Measure-Command { python main.py dataset/held_out_pep_noedd/submission.json }

# Time a single mock submission
$env:ORION_LLM_PROVIDER="mock"; $env:ORION_EXTRACTION_VOTES="1"
Measure-Command { python main.py dataset/held_out_pep_noedd/submission.json }
```

## Results

| Run | Accuracy | Per-pack wall time | 12-pack batch time | Cost estimate |
|---|---:|---:|---:|---|
| **Real LLM** (gpt-4o-mini, 3 votes) | **9/12 (75%)** | ~18.3 s (single-pack) | ~3.5 min (observed run fits in 5 min) | ~$0.001–$0.003/pack |
| **Mock** (keyword heuristic, offline) | 11/12 (92%) | ~0.15 s (batch) | 1.7 s | $0 |

The real-LLM run exactly meets the 75% held-out floor defined in CI. The mock run is a wiring/regression check, not a generalization claim.

## Manual baseline and hours saved

| Assumption | Value |
|---|---|
| Manual review per submission | 4–6 h (reading 3–12 docs + cross-referencing + rationale) |
| ORION extraction + scoring per submission | ~18 s (real LLM) / ~0.15 s (mock) |
| Monthly volume | 50 submissions |
| **Manual total** | 200–300 h/month |
| **ORION extraction total** | ~15 min/month (real LLM) |
| **Estimated time saved** | ~199–299 h/month |

*Assumptions: one review cycle per submission; time excludes human deliberation and override; real-LLM batch is sequential; per-pack time will rise if document size/LLM latency increases.*

## Worked cases

### Case 1 — PEP without dedicated EDD file (`held_out_pep_noedd`)

**Cascade Payments UAB.** The AML policy *states* that PEP EDD evidence is "on record under separate procedures," but no dedicated PEP-EDD document is in the upload. The real LLM extracted:

```json
{
  "has_pep": true,
  "missing_docs": ["PEP enhanced due diligence evidence"],
  "followup_questions": [
    "One or more key personnel are politically exposed persons (PEPs). Enhanced due diligence evidence including source of wealth documentation is required.",
    "Missing document required: PEP enhanced due diligence evidence."
  ]
}
```

**Outcome:** `CONDITIONAL` (composite 2.0). A pure checklist that only verifies "AML policy mentions PEPs" could easily mark this complete; ORION treats the missing attachment as a missing doc.

### Case 2 — Missing documents push outcome to DEFER (`held_out_defer_gaps`)

The applicant left out several required documents. The real LLM correctly surfaced the missing-doc penalty and returned `DEFER` (composite 6.4). This is the fail-closed behavior: absent evidence raises the score rather than being ignored.

### Case 3 — Failure case (`held_out_pep_edd`)

The pack is designed to be `CONDITIONAL` because a PEP exists and an EDD document is attached, but the real LLM predicted `APPROVE` (composite 1.6). The model under-weighted the PEP/EDD combo and counted the policy mention as sufficient. This is a known failure mode that keeps the system below the 80% target and shows where reviewer override remains mandatory.

## Caveats

- **Synthetic data:** all packs are fictional; real-world error rates will differ.
- **Rubric-calibrated:** the scoring rubric was tuned on the 23 in-sample packs; held-out accuracy is the honest generalization signal.
- **Stochastic:** real-LLM numbers can move ±1–2 packs between runs because extraction is probabilistic.
- **No live reviewer data:** we do not yet measure override rate, false positive rate, or time-to-decision in production.

## Recommended success metrics for a real pilot

All are measurable from existing logs/DB:

| Metric | How to measure | Target for a 50-submission/month team |
|---|---|---|
| Minutes per extraction | `jobs.timing.total_ms` / 60000 | < 5 min median |
| Reviewer override rate | `reviews` table where `status = OVERRIDDEN` / total reviewed | 5–15% (lower if AI is too rigid, higher if it is unreliable) |
| Audit completeness | every row has `input_hash`, `dimension_scores`, `authorization_level`, `review.reviewer_id` | 100% |
| Held-out accuracy regression | `python evaluate.py --check-min-accuracy 0.75` | ≥ 75% |
| Time saved vs manual | compare manual-hour estimate to extraction time | ≥ 80% reduction in document-reading time |

## What this means for ORION’s evaluation profile

- **Impact:** moves from "claimed" to "measured on a held-out set with explicit time-saved assumptions."
- **Innovation:** remains a hybrid LLM+rules design; the pilot validates the *operational* claim (minutes per review) rather than algorithmic novelty.
- **Scalability:** results are still single-machine; the pilot architecture in `docs/SDD.md` M7 and `docs/OPERATIONS.md` define the bounded single-team deployment path.
