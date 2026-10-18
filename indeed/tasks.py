import frappe
from frappe.utils import add_to_date, cint, now_datetime

from indeed.jobs import enqueue_sync
from indeed.utils import get_settings, is_enabled


def retry_pending_jobs():
	settings = get_settings()
	if not is_enabled("enable_job_publishing"):
		return

	max_attempts = cint(settings.max_attempts) or 5
	stale_before = add_to_date(now_datetime(), minutes=-30)

	rows = frappe.get_all(
		"Indeed Job Sync",
		filters={"status": ["in", ["Queued", "Failed"]], "next_retry_on": ["<=", now_datetime()]},
		fields=["name", "status", "attempt_count", "last_attempt_on", "modified"],
		limit=25,
	)

	queued_cutoff = add_to_date(now_datetime(), minutes=-10)
	for row in rows:
		if cint(row.attempt_count) >= max_attempts:
			continue
		if row.status == "Queued" and row.modified and row.modified > queued_cutoff:
			# freshly queued; a worker has not picked it up yet
			continue
		if row.status == "Queued" and row.last_attempt_on and row.last_attempt_on > stale_before:
			continue
		enqueue_sync(row.name)


def sync_applications():
	from indeed.applications import sync_applications as run

	run()


def cleanup_logs():
	settings = get_settings()
	days = cint(settings.log_retention_days) or 30
	cutoff = add_to_date(now_datetime(), days=-days)
	frappe.db.delete("Indeed Sync Log", {"creation": ["<", cutoff]})
