# Testing

## 1. Local unit tests

The suite is framework-light: `test_utils.py` and `test_payload.py` need no database rows, and
`test_jobs.py` mocks `frappe.db.get_value`.

```bash
cd ~/frappe-bench
bench --site <site> set-config allow_tests true
bench --site <site> run-tests --app indeed --skip-before-tests
```

`--skip-before-tests` skips the erpnext/hrms `before_tests` hooks (they write Singles and can deadlock
on a busy dev site). Run each module individually while iterating:

```bash
bench --site <site> run-tests --module indeed.tests.test_utils --skip-before-tests
bench --site <site> run-tests --module indeed.tests.test_payload --skip-before-tests
bench --site <site> run-tests --module indeed.tests.test_jobs --skip-before-tests
```

## 2. Lint + format (what the Linters workflow runs)

```bash
cd apps/indeed
ruff check .
ruff format --check .
npx --yes eslint@8.44.0 --quiet indeed/public/js
npx --yes prettier@2.7.1 --check "indeed/public/js/**/*.js"
pre-commit run --all-files
```

## 3. Migration / install check

```bash
cd ~/frappe-bench
bench --site <site> migrate
./env/bin/python - <<'PY'
import frappe
frappe.init(site="<site>", sites_path="sites"); frappe.connect()
print([d for d in ("Indeed Settings","Indeed Job Sync","Indeed Sync Log","Indeed Application")
       if frappe.db.exists("DocType", d)])
print(frappe.get_all("Custom Field", filters={"dt":"Job Opening","fieldname":["like","indeed%"]}, pluck="fieldname"))
print(frappe.get_all("Custom Field", filters={"dt":"Job Applicant","fieldname":["like","indeed%"]}, pluck="fieldname"))
PY
```

## 4. End-to-end without Indeed credentials (mocked transport)

Publish flow:

```python
import frappe
from unittest.mock import patch

frappe.init(site="<site>", sites_path="sites")
frappe.connect()
frappe.set_user("Administrator")

opening = frappe.get_doc(
	{
		"doctype": "Job Opening",
		"job_title": "Indeed Smoke Test Engineer",
		"company": frappe.db.get_value("Company", {}, "name"),
		"designation": frappe.db.get_value("Designation", {}, "name"),
		"status": "Open",
		"publish_to_indeed": 1,
	}
).insert(ignore_permissions=True)

from indeed import jobs

with patch(
	"indeed.jobs.IndeedClient.execute",
	return_value={"jobPostingCreate": {"jobPosting": {"id": "indeed-smoke-1"}}},
):
	jobs.run_sync(opening.name)

print(frappe.get_doc("Indeed Job Sync", opening.name).status)  # Synced
```

Expire flow: set `opening.status = "Closed"`, save, then patch `execute` to return
`{"jobPostingExpire": {"jobPosting": {"id": "indeed-smoke-1"}}}` and call
`jobs.run_sync(opening.name)`; expect `Expired` and both `indeed_job_id` fields cleared.

Application flow:

```python
from indeed import applications

payload = {
	"id": "app-smoke-1",
	"jobKey": opening.name,
	"candidate": {"id": "cand-1", "name": "Smoke Candidate", "email": "smoke@example.com"},
	"resumeUrl": "https://example.com/cv.pdf",
}
applications.process_application(payload)
applications.process_application(payload)  # idempotent: same Indeed Application
```

## 5. End-to-end with real Indeed credentials

1. **Connection** — Indeed Settings → *Test Connection*. Executes `query Ping { __typename }`;
   a green alert means OAuth + GraphQL both work. Inspect `Indeed Sync Log` (`operation=test_connection`).
2. **Publish** — create a Job Opening with *Publish to Indeed* checked, save, then Job Opening →
   *Publish to Indeed*. Confirm `Indeed Job Sync.status = Synced`, `indeed_job_id` populated, and the
   posting appears on Indeed.
3. **Update** — change the description and save; a second `Indeed Sync Log` row with
   `operation=job_update` must appear. Saving again with no changes must produce no new row.
4. **Expire** — *Expire on Indeed* (or set status to `Closed`). Posting disappears on Indeed;
   `Indeed Job Sync.status = Expired`.
5. **Webhook** — generate a signature locally and post it:

   ```bash
   SECRET='<webhook_secret>'
   BODY='{"id":"app-live-1","jobKey":"HR-OPN-2026-0001","candidate":{"name":"A","email":"a@example.com"}}'
   SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" -r | cut -d' ' -f1)
   curl -sS -X POST 'https://<site>/api/method/indeed.api.webhook' \
     -H 'Content-Type: application/json' -H "X-Indeed-Signature: sha256=$SIG" -d "$BODY"
   # {"message":{"status":"accepted"}}
   ```

   Then check: `Indeed Application` row `Linked`, a `Job Applicant` with `from_indeed = 1`,
   `source = Indeed`, and `Indeed Sync Log` entry `direction=Inbound, operation=webhook`.

   Negative case: repeat with a wrong signature → HTTP 403 `Invalid signature` and a `Failed` log row.

6. **Polling fallback** — Indeed Settings → *Sync Applications Now*, or wait for the hourly
   `indeed.tasks.sync_applications`. Cursor advances in `Indeed Job Sync.application_cursor`.
7. **Retries** — set an invalid `client_secret`, save a Job Opening, run
   `bench --site <site> execute indeed.tasks.retry_pending_jobs`; the sync row shows
   `status = Failed`, a `last_error`, and `next_retry_on` set. Fix the secret and use
   *Retry Now* on the Indeed Job Sync form.

## 6. CI/CD

`.github/workflows/ci.yml` runs on every push to `develop`/`main` and every pull request:

1. spins up MariaDB 10.6 and two Redis instances (ports 3306, 13000, 11000);
2. `bench init` on Python 3.10;
3. `bench get-app indeed $GITHUB_WORKSPACE` + `bench get-app hrms --branch version-15`;
4. `bench new-site test_site`, then `install-app hrms` and `install-app indeed`;
5. `bench --site test_site run-tests --app indeed --skip-before-tests`.

`.github/workflows/linter.yml` runs on every pull request: pre-commit (ruff, prettier, eslint, JSON/YAML
syntax), Frappe Semgrep rules, and `pip-audit` on dependencies.

Any `## 2` / `## 1` failure reproduces the CI failure locally; run `pre-commit run --all-files` before
pushing.
