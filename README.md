### Indeed

ERPNext / Frappe HRMS ↔ Indeed integration (both directions).

- **Outbound:** Job Opening save → Indeed GraphQL job create / update / expire, queued with retries.
- **Inbound:** Indeed applications → `Job Applicant` (webhook, with hourly polling fallback).

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design and [TESTING.md](TESTING.md) for verification.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench get-app hrms --branch version-15
bench --site $SITE install-app hrms
bench --site $SITE install-app indeed
```

### Configuration

Open **Indeed Settings** and fill in:

| Field | Purpose |
| --- | --- |
| `client_id` / `client_secret` | OAuth2 client-credentials pair issued by Indeed |
| `scope` | Defaults to `employer_access` |
| `job_country` | ISO 3166-1 alpha-2 code used in the job location |
| `auto_publish_new_jobs` | Publish every open Job Opening (otherwise opt in per record) |
| `webhook_secret` | HMAC secret; inbound webhooks are rejected when empty |
| `*_mutation` / `*_query` | Optional GraphQL overrides for your Indeed partner schema |

Register the webhook URL with Indeed:

```
https://<your-site>/api/method/indeed.api.webhook
```

Per job control lives on the Job Opening form (**Indeed** section + Publish/Expire buttons). Sync
state lives in **Indeed Job Sync**; request/response history in **Indeed Sync Log**.

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/indeed
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs frappe + hrms + this app and runs the test suite on every push and pull request.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.

### License

mit
