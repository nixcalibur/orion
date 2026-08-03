# ORION — Data Privacy & Retention

**Status:** applies to the current demo/research prototype. ORION is not a
certified production compliance system.

## What data ORION handles

| Store | Location (default) | Contents | Lifecycle |
|---|---|---|---|
| Upload staging | `ORION_UPLOAD_DIR` (`uploads/`) | Submitted JSON + supporting docs staged for a pipeline run | Ephemeral: created per run, git-ignored. **Not** a durable store. |
| SQLite review store | `ORION_DB_PATH` (`data/orion.db`) | Latest assessment per submission + reviewer accept/override decisions | Retained until deleted. Contains extracted risk profiles and review decisions. |
| Audit log | `audit.jsonl` | Append-only JSONL per run: input hash, model, prompt hash, extracted profile, scores, delivery outcome | Retained until deleted. Replay/reproducibility record. |

## Retention policy (recommended)

- **Uploads:** treated as temporary scratch. Set `ORION_UPLOAD_DIR` to a
  short-lived/tmp location in any shared deployment and purge on a schedule
  (e.g., 7-day TTL). The API never reads back from `uploads/` after a run.
- **Review store & audit log:** keep for the applicable regulatory retention
  window in your jurisdiction (e.g., 5–7 years for AML-adjacent records), then
  delete. Both files are plaintext — protect them with filesystem permissions
  (`0600`/restricted ACL) and do not commit them to version control (both are
  git-ignored).
- **API keys / model metadata:** the audit log stores the model name and
  system fingerprint, not the API key. Never log `OPENAI_API_KEY`.

## Git history note

Earlier commits accidentally tracked uploaded test fixtures under `uploads/`
(fictional entities such as "ClearLedger Systems 39", plus a developer scratch
note). These were removed from tracking and `uploads/` is now git-ignored.
The files were **synthetic test data containing no real personal or financial
information**; they remain recoverable only inside git history. If ORION is
ever used with real submissions, uploads must be staged outside the repository
and the repo must never contain customer data.

## Handling real data

If ORION is ever pointed at real submissions:

1. Do not stage uploads inside the git repo (set `ORION_UPLOAD_DIR` outside it).
2. Encrypt the SQLite store and audit log at rest.
3. Apply access controls at the API (`ORION_API_KEY`) and filesystem.
4. Define a retention/deletion schedule and a data-subject/erasure procedure
   before processing any real personal data.
5. Review whether the deployment is subject to GDPR / local AML record-keeping
   obligations and scope the review accordingly.
