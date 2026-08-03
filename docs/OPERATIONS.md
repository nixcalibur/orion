# ORION — Operations runbook (bounded pilot)

This runbook covers running ORION as a **single-team pilot**: one deployment, one API key, 1–5 concurrent reviewers, SQLite on local disk. It does not cover multi-tenant, SSO, or horizontal scale-out.

## Environment variables

| Variable | Purpose | Default | Change risk |
|---|---|---|---|
| `OPENAI_API_KEY` | LLM extraction | *required* | Without it, set `ORION_LLM_PROVIDER=mock` |
| `ORION_LLM_PROVIDER` | `openai` or `mock` | `openai` | Mock is offline but uses keyword heuristics |
| `ORION_EXTRACTION_VOTES` | Majority-vote passes | `3` | Lower = cheaper, less stable |
| `ORION_DB_PATH` | SQLite file | `data/orion.db` | Must be on persistent storage |
| `ORION_UPLOAD_DIR` | Staged uploads | `uploads` | Must be on persistent storage |
| `ORION_API_KEY` | Optional API-key auth | unset | Set for shared/demo access |
| `ORION_MAX_UPLOAD_SIZE` | Per-file upload cap | `52428800` (50 MB) | Lower to reduce disk/ingest load |
| `ORION_JOB_TTL_MINUTES` | In-memory job cache TTL | `60` | Only affects cache, not SQLite |
| `ORION_RUNNING_JOB_TIMEOUT_MINUTES` | Stale-running threshold | `10` | Jobs older than this are shown as error after restart |
| `ORION_THRESHOLD_REJECT/DEFER/CONDITIONAL` | Authorization thresholds | `9.0/4.5/2.0` | Change = business-rule change |
| `REVIEW_API_URL` | External delivery target | `https://httpbin.org/post` | Set empty to skip delivery |

## Backup and restore

### What to back up

1. `ORION_DB_PATH` (default `data/orion.db`) — latest assessments, reviews, durable jobs.
2. `audit.jsonl` — append-only audit log (if `AUDIT_JSONL` is enabled).
3. `ORION_UPLOAD_DIR` (default `uploads/`) — staged submission files.

### Simple backup (daily)

```bash
# Linux/macOS
mkdir -p backups/$(date +%Y-%m-%d)
cp data/orion.db backups/$(date +%Y-%m-%d)/
cp audit.jsonl backups/$(date +%Y-%m-%d)/ 2>/dev/null || true
tar czf backups/$(date +%Y-%m-%d)/uploads.tar.gz uploads/

# PowerShell
$ts = Get-Date -Format "yyyy-MM-dd"
New-Item -ItemType Directory -Path "backups/$ts" -Force | Out-Null
Copy-Item data/orion.db "backups/$ts/" -ErrorAction SilentlyContinue
Copy-Item audit.jsonl "backups/$ts/" -ErrorAction SilentlyContinue
Compress-Archive -Path uploads -DestinationPath "backups/$ts/uploads.zip" -Force
```

### Restore

```bash
# Stop the API container/process.
cp backups/YYYY-MM-DD/orion.db data/orion.db
cp backups/YYYY-MM-DD/audit.jsonl audit.jsonl  # or skip and keep current
# Extract uploads backup to uploads/
```

> **Note:** restoring `orion.db` to an older point in time while keeping a newer `audit.jsonl` is safe because `audit.jsonl` is append-only and `orion.db` is only the latest state. Restoring uploads is only needed if you want to re-run or inspect original files.

## Purge uploads

Uploads accumulate in `uploads/` and in the `jobs` table. They are not auto-pruned. For a bounded pilot, purge monthly:

```bash
# 1. Stop the API.
# 2. Move old upload directories to an archive or delete.
Remove-Item -Recurse -Force uploads/orion_upload_*
# 3. Vacuum SQLite to reclaim space.
sqlite3 data/orion.db "VACUUM;"
# 4. Restart the API.
```

> Do not delete uploads for active reviews unless you have backed them up. The DB references their paths only for re-run; the audit log still contains the input hash and extracted text.

## Rotate API keys

1. Generate a new key.
2. Update `ORION_API_KEY` in the environment / `.env`.
3. Restart the API process/container.
4. Distribute the new key to reviewers (or update `VITE_API_KEY` for the UI).
5. There is no session state to invalidate; the key is checked on every request.

## Rotate the OpenAI key

1. Update `OPENAI_API_KEY` in the environment / `.env`.
2. Restart the API. In-flight extractions using the old key will fail; they are logged and retried on the next start.

## Failure modes and responses

| Symptom | Likely cause | Response |
|---|---|---|
| API returns 401 | Wrong/missing `ORION_API_KEY` | Verify header `Authorization: Bearer <key>` or `X-API-Key: <key>` |
| Assessment stuck in `running` >10 min | Process crashed/restarted | GET returns error after `ORION_RUNNING_JOB_TIMEOUT_MINUTES`; resubmit the assessment |
| Assessment 404 but job exists | Pipeline returned no result | Check logs; usually extraction/schema failure; fix input and resubmit |
| `audit.jsonl` grows very large | Append-only log | Rotate/archive the file; ORION will create a new one |
| SQLite "database is locked" | Too many concurrent writes | Reduce concurrency; for the bounded pilot, 1–5 reviewers should not hit this |
| Disk full on uploads | Large files / no purge | Increase disk or reduce `ORION_MAX_UPLOAD_SIZE`; purge old uploads |
| Delivery status `failed` | `REVIEW_API_URL` unreachable | Check network; set `REVIEW_API_URL=""` to skip delivery during tests |

## Health checks

```bash
curl http://localhost:8000/health
# Expected: {"status": "ok", "service": "orion"}
```

`/health` is intentionally unauthenticated.

## Monitoring for the bounded pilot

The simplest useful checks:

1. **Disk space** on the volume holding `ORION_DB_PATH` and `ORION_UPLOAD_DIR`.
2. **Job queue depth:** query for running/error jobs:
   ```bash
   sqlite3 data/orion.db "SELECT status, COUNT(*) FROM jobs GROUP BY status;"
   ```
3. **Recent assessment volume:**
   ```bash
   sqlite3 data/orion.db "SELECT COUNT(*), authorization_level FROM assessments GROUP BY authorization_level;"
   ```
4. **Override rate** (human disagreement with AI recommendation):
   ```bash
   sqlite3 data/orion.db "SELECT COUNT(*) FROM reviews WHERE status = 'OVERRIDDEN';"
   ```

## Out of scope for this pilot

The following are explicitly not covered here because they are out of scope for the bounded pilot:

- Multi-tenant isolation or per-organization data separation.
- Single sign-on (SSO) or role-based access control (RBAC).
- Horizontal scaling / load balancing.
- Encrypted-at-rest database beyond filesystem encryption.
- Automated failover / high availability.

For these, treat ORION as a component that feeds a larger platform rather than the platform itself.
