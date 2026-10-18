# Integration Architecture

The app is a self-contained Frappe/HRMS integration. Nothing calls Indeed during a user request
except the two explicit "now" buttons, so a slow or failing Indeed API never blocks Desk.

```
					┌──────────────────────────────────────┐
	Job Opening  ──►│ indeed.jobs.on_job_opening_update     │ (doc_events: on_update)
	(save)           │   desired_action() → Publish/Update/Expire │
					│   needs_sync(): payload_hash comparison    │
					└───────────────┬──────────────────────┘
									│ queue_sync() → frappe.enqueue(after_commit)
									▼
					┌──────────────────────────────────────┐
					│ Indeed Job Sync (state machine)      │
					│ Pending → Queued → Synced/Failed/     │
					│ Skipped/Expired                       │
					└───────────────┬──────────────────────┘
									▼
					┌──────────────────────────────────────┐
					│ indeed.jobs.run_sync (RQ long queue)  │
					│ publish() / expire()                  │
					└───────────────┬──────────────────────┘
									▼
					┌──────────────────────────────────────┐
					│ indeed.client.IndeedClient            │
					│  OAuth2 client_credentials (cached)   │
					│  GraphQL POST, 401-refresh, 429/5xx   │
					│  exponential backoff (max 3 attempts) │
					└───────────────┬──────────────────────┘
									▼
						https://apis.indeed.com/graphql
						https://apis.indeed.com/oauth/v2/tokens

	Indeed ──POST /api/method/indeed.api.webhook──► HMAC-SHA256 verify (raw body)
													│
													▼
					┌──────────────────────────────────────┐
					│ indeed.applications.handle_webhook    │
					│  extract_applications() → process_*   │
					└───────────────┬──────────────────────┘
									▼
					Indeed Application (autoname = application id)
						→ resolve_job_opening(jobKey)
						→ create_job_applicant() (dedupe email + Job Opening)
						→ status Linked / Skipped / Failed

	Fallback polling: scheduler hourly → indeed.tasks.sync_applications
					  → jobApplications(jobKey, after: cursor)
					  → cursor stored on Indeed Job Sync.application_cursor
```

## Design decisions

- **One state row per Job Opening.** `Indeed Job Sync` is autonamed by `job_opening`, so the record
  is a natural queue/state machine and its fields are queried by name without joins.
- **Payload hash as the idempotency key.** `payload_hash(payload)` is a sorted-JSON SHA-256; an
  `Update` that produces an identical hash is skipped, which prevents update storms on unrelated
  saves (e.g. someone editing a custom field).
- **Indeed job key == Job Opening name.** `get_job_key()` falls back to the document name so publish,
  update and expire always target the same key even if the title/route changes later.
- **Remote id is cleared on expire.** After `jobPostingExpire`, `indeed_job_id` is nulled on both the
  sync row and the Job Opening, so reopening a posting creates a fresh one instead of updating an
  expired one.
- **Retries live in the database, not only in RQ.** `next_retry_on` + `attempt_count` make retries
  survive worker restarts; `indeed.tasks.retry_pending_jobs` re-enqueues due rows and also rescues
  `Queued` rows whose worker died (`modified` older than 10 minutes).
- **Webhook fails closed.** No `webhook_secret` → HTTP 403. Signature is HMAC-SHA256 over the raw
  request body, compared with `hmac.compare_digest`, accepting a `sha256=` prefix.
- **Inbound idempotency by application id.** `Indeed Application.indeed_application_id` is unique and
  used as the autoname, so duplicate webhook deliveries return the existing record.
- **Secrets stay in `Password` fields.** `client_secret` and `webhook_secret` are read with
  `get_password()` and are never written to `Indeed Sync Log`.
- **GraphQL documents are overridable.** Every mutation/query has a hard-coded default plus a `Code`
  field in `Indeed Settings`, so a partner-specific schema change is a configuration edit, not a
  release.
- **Auditability.** `Indeed Sync Log` stores request/response bodies (truncated to
  `max_log_body_chars`), HTTP status, duration, attempt count and the failing error; the daily task
  prunes rows older than `log_retention_days`.

## Boundary rules

- Custom fields on `Job Opening` and `Job Applicant` are created by the patch
  `indeed.patches.v1_0.create_custom_fields`, never by editing HRMS.
- `on_trash` performs a best-effort synchronous expiry because the Job Opening and its sync row
  disappear immediately after; every other Indeed call is asynchronous.
- `indeed.api.webhook` is the only `allow_guest` entry point; every other whitelisted method runs
  with normal Frappe role checks (`HR Manager` / `System Manager`).
