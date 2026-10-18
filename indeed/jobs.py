import frappe
from frappe import _
from frappe.utils import add_to_date, cint, now_datetime

from indeed.client import IndeedClient, IndeedError
from indeed.payload import build_job_payload, get_job_key
from indeed.utils import (
	DEFAULT_JOB_CREATE_MUTATION,
	DEFAULT_JOB_EXPIRE_MUTATION,
	DEFAULT_JOB_UPDATE_MUTATION,
	extract_job_id,
	get_operation,
	get_settings,
	is_enabled,
	payload_hash,
)


def desired_action(doc):
	"""Return the action the Job Opening currently needs, or None."""
	settings = get_settings()
	if not (cint(doc.get("publish_to_indeed")) or cint(settings.auto_publish_new_jobs)):
		return None
	if (doc.get("status") or "Open") != "Open":
		return "Expire"
	has_posting = bool(
		doc.get("indeed_job_id") or frappe.db.get_value("Indeed Job Sync", doc.name, "indeed_job_id")
	)
	return "Update" if has_posting else "Publish"


def on_job_opening_update(doc, method=None):
	if not is_enabled("enable_job_publishing"):
		return
	action = desired_action(doc)
	if not action:
		return
	sync = get_or_create_sync(doc.name)
	if action == "Expire" and not sync.indeed_job_id:
		return
	if sync.status == "Queued" and sync.desired_action == action:
		return
	if action != "Expire" and not needs_sync(doc, sync):
		return
	queue_sync(doc.name, action)


def on_job_opening_trash(doc, method=None):
	"""Best-effort synchronous expiry: the Job Opening (and its links) disappear right after."""
	from indeed.utils import log_sync

	if not is_enabled("enable_job_publishing"):
		return

	sync = frappe.db.get_value(
		"Indeed Job Sync", doc.name, ["name", "indeed_job_id", "job_key"], as_dict=True
	)
	if not sync or not sync.indeed_job_id:
		return
	try:
		client = IndeedClient()
		settings = get_settings()
		client.execute(
			get_operation(settings, "job_expire_mutation", DEFAULT_JOB_EXPIRE_MUTATION),
			{"jobKey": sync.job_key or get_job_key(doc), "jobPostingId": sync.indeed_job_id},
			operation="job_expire",
			reference_doctype="Job Opening",
			reference_name=doc.name,
		)
	except Exception as exc:
		log_sync(
			"Failed",
			operation="job_expire",
			error=str(exc),
			reference_doctype="Job Opening",
			reference_name=doc.name,
		)


def get_or_create_sync(job_opening):
	name = frappe.db.get_value("Indeed Job Sync", {"job_opening": job_opening}, "name")
	if name:
		return frappe.get_doc("Indeed Job Sync", name)

	doc = frappe.get_doc(
		{
			"doctype": "Indeed Job Sync",
			"job_opening": job_opening,
			"status": "Pending",
			"job_key": job_opening,
		}
	)
	try:
		doc.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		return frappe.get_doc("Indeed Job Sync", job_opening)
	return doc


def needs_sync(doc, sync):
	if not sync.indeed_job_id:
		return True
	if sync.status not in ("Synced",):
		return True
	try:
		payload = build_job_payload(doc)
	except Exception:
		frappe.log_error(
			title=f"Indeed: could not build payload for {doc.name}",
			message=frappe.get_traceback(),
		)
		return True
	return payload_hash(payload) != (sync.payload_hash or "")


def queue_sync(job_opening, action=None):
	sync = get_or_create_sync(job_opening)
	sync.desired_action = action or "Publish"
	sync.status = "Queued"
	sync.next_retry_on = now_datetime()
	sync.save(ignore_permissions=True)
	frappe.db.set_value("Job Opening", job_opening, "indeed_sync_status", _("Queued"))
	try:
		enqueue_sync(sync.name)
	except Exception as exc:
		sync.status = "Failed"
		sync.next_retry_on = add_to_date(now_datetime(), minutes=5)
		sync.last_error = str(exc)[:1000]
		sync.save(ignore_permissions=True)
		frappe.log_error(
			title=f"Indeed: could not queue sync for {job_opening}", message=frappe.get_traceback()
		)


def enqueue_sync(job_sync):
	frappe.enqueue(
		"indeed.jobs.run_sync",
		queue="long",
		timeout=600,
		job_sync=job_sync,
		enqueue_after_commit=True,
	)


def run_sync(job_sync):
	sync = frappe.get_doc("Indeed Job Sync", job_sync)
	if not is_enabled("enable_job_publishing"):
		if sync.status == "Queued":
			sync.status = "Pending"
			sync.next_retry_on = None
			sync.save(ignore_permissions=True)
		return

	if not frappe.db.exists("Job Opening", sync.job_opening):
		_mark(sync, "Skipped", error=_("Job Opening no longer exists"))
		return

	opening = frappe.get_doc("Job Opening", sync.job_opening)
	action = sync.desired_action or "Publish"
	sync.attempt_count = cint(sync.attempt_count) + 1
	sync.last_attempt_on = now_datetime()

	try:
		if action == "Expire":
			expire(opening, sync)
		else:
			publish(opening, sync, action)
	except IndeedError as exc:
		handle_failure(sync, str(exc))
	except Exception as exc:
		frappe.log_error(
			title=f"Indeed: sync failed for {sync.job_opening}",
			message=frappe.get_traceback(),
		)
		handle_failure(sync, str(exc))


def publish(opening, sync, action):
	settings = get_settings()
	payload = build_job_payload(opening)
	digest = payload_hash(payload)

	if action == "Update" and sync.status == "Synced" and sync.payload_hash == digest:
		return

	client = IndeedClient(settings)
	variables = {"input": dict(payload)}
	operation = "job_create"
	query = get_operation(settings, "job_create_mutation", DEFAULT_JOB_CREATE_MUTATION)

	if sync.indeed_job_id:
		operation = "job_update"
		query = get_operation(settings, "job_update_mutation", DEFAULT_JOB_UPDATE_MUTATION)
		variables["input"]["id"] = sync.indeed_job_id
		variables["jobPostingId"] = sync.indeed_job_id

	data = client.execute(
		query,
		variables,
		operation=operation,
		reference_doctype="Job Opening",
		reference_name=opening.name,
	)

	indeed_id = extract_job_id(data) or sync.indeed_job_id
	if not indeed_id:
		raise IndeedError(_("Indeed did not return a job id for the new posting"))
	_mark(
		sync,
		"Synced",
		indeed_job_id=indeed_id,
		job_key=payload.get("jobKey"),
		payload_hash=digest,
		response_snippet=data,
	)
	frappe.db.set_value(
		"Job Opening",
		opening.name,
		{
			"indeed_job_key": payload.get("jobKey"),
			"indeed_job_id": indeed_id,
			"indeed_sync_status": _("Synced"),
			"indeed_last_synced_on": now_datetime(),
		},
		update_modified=False,
	)


def expire(opening, sync):
	if not sync.indeed_job_id:
		_mark(sync, "Skipped", error=_("No Indeed posting to expire"))
		frappe.db.set_value(
			"Job Opening", opening.name, "indeed_sync_status", _("Not Published"), update_modified=False
		)
		return

	settings = get_settings()
	client = IndeedClient(settings)
	data = client.execute(
		get_operation(settings, "job_expire_mutation", DEFAULT_JOB_EXPIRE_MUTATION),
		{"jobKey": sync.job_key or get_job_key(opening), "jobPostingId": sync.indeed_job_id},
		operation="job_expire",
		reference_doctype="Job Opening",
		reference_name=opening.name,
	)
	_mark(sync, "Expired", payload_hash=None, response_snippet=data)
	frappe.db.set_value("Indeed Job Sync", sync.name, "indeed_job_id", None, update_modified=False)
	frappe.db.set_value(
		"Job Opening",
		opening.name,
		{
			"indeed_job_id": None,
			"indeed_sync_status": _("Expired"),
			"indeed_last_synced_on": now_datetime(),
		},
		update_modified=False,
	)


def handle_failure(sync, error):
	sync.attempt_count = cint(sync.attempt_count) or 1
	settings = get_settings()
	max_attempts = cint(settings.max_attempts) or 5
	delay = cint(settings.retry_delay_minutes) or 15
	next_retry = add_to_date(now_datetime(), minutes=delay * sync.attempt_count)
	if sync.attempt_count >= max_attempts:
		next_retry = None
	sync.status = "Failed"
	sync.next_retry_on = next_retry
	sync.last_error = str(error)[:1000]
	sync.save(ignore_permissions=True)
	frappe.db.set_value(
		"Job Opening",
		sync.job_opening,
		"indeed_sync_status",
		_("Failed"),
		update_modified=False,
	)


def _mark(
	sync, status, indeed_job_id=None, job_key=None, payload_hash=None, response_snippet=None, error=None
):
	sync.status = status
	sync.last_error = (error or "")[:1000] or None
	sync.next_retry_on = None
	if indeed_job_id is not None:
		sync.indeed_job_id = indeed_job_id
	if job_key:
		sync.job_key = job_key
	if payload_hash is not None:
		sync.payload_hash = payload_hash
	if response_snippet is not None:
		sync.response_snippet = frappe.as_json(response_snippet, indent=1)[:20000]
	sync.save(ignore_permissions=True)
