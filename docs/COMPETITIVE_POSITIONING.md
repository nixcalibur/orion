# ORION — Competitive positioning

ORION is a **bounded compliance-review assistant**: LLM reads documents, deterministic rules compute risk, and a human always makes the final decision. It is not a general-purpose RegTech platform. This note compares it to three common alternatives and states what is (and is not) novel.

## Alternatives landscape

| Alternative | Typical approach | Strength | Weakness relative to ORION |
|---|---|---|---|
| **Pure LLM assistants** (chat-with-docs, "should we approve this?") | Model reasons end-to-end and returns a recommendation | Fast to set up; handles unstructured language | Score/opinion is opaque, changes between runs, hard to audit, may cite nonexistent evidence |
| **Rules-only checklists** (spreadsheet, policy checklist) | Reviewer ticks boxes; system sums a score | Fully deterministic; easy to explain | Misses content in free-text documents; cannot cross-check "policy says X" vs "document proves X" |
| **Generic document AI** (OCR + entity extraction) | Extracts named entities, clauses, tables | Good at layout/structure retrieval | No domain-specific scoring; no fail-closed tie handling; no human override + audit replay |

## What ORION does differently

These differentiators are already implemented in code:

1. **LLM extracts, rules decide, human overrides.**
   - The model never emits the final `APPROVE/CONDITIONAL/DEFER/REJECT` outcome. That is computed by version-controlled Python in `score.py`. The UI explicitly shows this separation: *"AI extracts facts; rules compute the score; you decide."*

2. **Evidence verification before scoring.**
   - Every evidence excerpt is checked against the ingested document text (`verify_evidence`). Citations that do not match their source are dropped, not replaced.

3. **Fail-closed tie handling.**
   - When majority-vote extraction ties, the system picks the worst-case value. When hard rules match (criminal flag, major regulatory history), the system overrides the numeric score and labels the reason in the UI/API as `fail_closed_reasons`.

4. **Human override + immutable replay.**
   - Reviewer accepts or overrides via `POST /assessments/{id}/review`. Each decision is paired with the `input_hash` of the exact inputs. If the submission is reassessed, the review is marked `STALE` instead of silently reused. The `audit.jsonl` record contains input hash, model, prompt hash, scores, and delivery outcome — enough to replay the decision.

5. **Majority-vote extraction.**
   - `ORION_EXTRACTION_VOTES` (default 3) runs multiple independent extractions with different seeds. Scalar fields vote; ties fail closed. This directly addresses single-run LLM instability.

6. **Deterministic mock mode.**
   - `ORION_LLM_PROVIDER=mock` runs the same ingest→extract→score→audit path with a keyword extractor, so CI, demos, and regressions do not depend on an API key.

## What is *not* novel

- **Document parsing:** ORION uses standard libraries/docling for PDF/DOCX/XLSX/TXT. It does not invent a new parser.
- **SQLite + FastAPI:** a common, conservative persistence and API stack.
- **LLM extraction itself:** the novelty is in *how* the extraction is validated and combined with deterministic scoring, not in using an LLM to read text.
- **Horizontal scale:** ORION is explicitly single-tenant, single-machine for the bounded pilot.

## When ORION wins vs when another tool wins

| Scenario | Best fit |
|---|---|
| Need full workflow automation, multi-tenant SaaS, SSO, multi-region | Existing RegTech platform |
| Need flexible Q&A over submissions, no hard scoring rules | Pure LLM assistant |
| Need absolute determinism and have already-normalized structured data | Rules-only system |
| Need **auditable, repeatable extraction + deterministic scoring + human override** for a single team | ORION |

## Why this matters for evaluators

The project is not claiming a new model architecture or a breakthrough in document understanding. The innovation claim is **process-level**: a small, auditable pipeline that separates extraction from decision-making and makes every override traceable. The competitive positioning evidence is in the code (`extract.py` vote/merge, `score.py` deterministic rules, `audit.py` immutable records, `api.py` override/review endpoints) and in the evaluation harness (`evaluate.py` held-out accuracy).
