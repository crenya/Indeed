import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from indeed.client import IndeedClient, IndeedError
from indeed.utils import (
	DEFAULT_APPLICATION_QUERY,
	DEFAULT_APPLICATIONS_QUERY,
	deep_pick,
	find_first_key,
	get_operation,
	get_settings,
	is_enabled,
	log_sync,
	truncate,
)


def handle_webhook(payload):
	for application in extract_applications(payload):
		process_application(application)


def extract_applications(payload):
	if isinstance(payload, list):
		return [item for item in payload if isinstance(item, dict)]

	if not isinstance(payload, dict):
		return []

	for key in ("applications", "items"):
		value = payload.get(key)
		if isinstance(value, list):
			return [item for item in value if isinstance(item, dict)]

	if isinstance(payload.get("events"), list):
		applications = []
		for event in payload["events"]:
			if not isinstance(event, dict):
				continue
			data = event.get("data") or event.get("application") or event
			if isinstance(data, dict):
				applications.append(data)
		return applications

	if deep_pick(payload, "candidate", "candidateEmail", "applicant") and _application_id(payload):
		return [payload]

	application_id = _application_id(payload)
	if application_id:
		return [payload]

	return []


def _application_id(payload):
	value = deep_pick(
		payload,
		"id",
		"applicationId",
		"application.id",
		"application.applicationId",
	)
	return str(value) if value else None


def process_application(payload):
	application_id = _application_id(payload)
	if not application_id:
		log_sync(
			"Failed",
			direction="Inbound",
			operation="application",
			response_body=payload,
			error=_("Application payload has no id"),
		)
		return None

	if frappe.db.exists("Indeed Application", application_id):
		return frappe.get_doc("Indeed Application", application_id)

	record = frappe.get_doc(
		{
			"doctype": "Indeed Application",
			"indeed_application_id": application_id,
			"status": "Received",
			"received_on": now_datetime(),
			"payload": truncate(payload),
		}
	)

	try:
		populate(record, payload)
		record.insert(ignore_permissions=True)
	except Exception as exc:
		frappe.log_error(title=f"Indeed: application {application_id}", message=frappe.get_traceback())
		_save_failure(record, payload, application_id, str(exc))
	return record


def populate(record, payload):
	job_key = deep_pick(payload, "jobKey", "job.jobKey", "job.id")
	candidate_id = deep_pick(payload, "candidate.id", "candidateId", "applicant.id")
	name = deep_pick(
		payload,
		"candidate.name",
		"candidate.fullName",
		"candidateName",
		"applicant.name",
		"applicantName",
	)
	email = deep_pick(
		payload,
		"candidate.email",
		"candidateEmail",
		"applicant.email",
		"email",
	)
	phone = deep_pick(payload, "candidate.phone", "candidate.phoneNumber", "phone", "phoneNumber")
	resume_url = deep_pick(payload, "resumeUrl", "resume.url", "candidate.resumeUrl")
	cover_letter = deep_pick(payload, "coverLetter", "coverLetter.text", "coverLetterText")

	record.indeed_job_key = job_key
	record.candidate_id = candidate_id
	record.candidate_name = name
	record.candidate_email = email

	opening = resolve_job_opening(job_key)
	if not opening:
		record.status = "Skipped"
		record.error = _("No Job Opening found for Indeed job key {0}").format(job_key)
		return

	record.job_opening = opening
	applicant = create_job_applicant(
		opening=opening,
		name=name,
		email=email,
		phone=phone,
		resume_url=resume_url,
		cover_letter=cover_letter,
		application_id=record.indeed_application_id,
		candidate_id=candidate_id,
	)
	record.job_applicant = applicant
	record.status = "Linked"


def resolve_job_opening(job_key):
	if not job_key:
		return None
	if frappe.db.exists("Job Opening", job_key):
		return job_key
	return frappe.db.get_value("Indeed Job Sync", {"job_key": job_key}, "job_opening")


def ensure_source(source):
	source = source or "Indeed"
	if not frappe.db.exists("Job Applicant Source", source):
		frappe.get_doc(
			{
				"doctype": "Job Applicant Source",
				"source_name": source,
				"details": _("Applications received through Indeed"),
			}
		).insert(ignore_permissions=True)
	return source


def create_job_applicant(opening, name, email, phone, resume_url, cover_letter, application_id, candidate_id):
	settings = get_settings()
	existing = None
	if email:
		existing = frappe.db.get_value("Job Applicant", {"email_id": email, "job_title": opening}, "name")

	if existing:
		applicant = frappe.get_doc("Job Applicant", existing)
	else:
		applicant = frappe.get_doc(
			{
				"doctype": "Job Applicant",
				"applicant_name": name or email or _("Indeed Applicant"),
				"email_id": email or f"indeed+{application_id}@example.invalid",
				"phone_number": phone,
				"job_title": opening,
				"status": settings.application_status or "Open",
				"source": ensure_source(settings.default_source),
				"cover_letter": cover_letter,
				"resume_link": resume_url,
				"notes": _("Applied through Indeed (application {0})").format(application_id),
				"from_indeed": 1,
				"indeed_application_id": application_id,
				"indeed_candidate_id": candidate_id,
			}
		)
		applicant.insert(ignore_permissions=True)

	changes = {}
	if not applicant.get("from_indeed"):
		changes["from_indeed"] = 1
	if application_id and not applicant.get("indeed_application_id"):
		changes["indeed_application_id"] = application_id
	if candidate_id and not applicant.get("indeed_candidate_id"):
		changes["indeed_candidate_id"] = candidate_id
	if resume_url and not applicant.get("resume_link"):
		changes["resume_link"] = resume_url
	if changes:
		frappe.db.set_value("Job Applicant", applicant.name, changes, update_modified=False)
	return applicant.name


def _save_failure(record, payload, application_id, error):
	log_sync(
		"Failed",
		direction="Inbound",
		operation="application",
		response_body=payload,
		error=error,
		reference_doctype="Indeed Application",
		reference_name=application_id,
	)
	if frappe.db.exists("Indeed Application", application_id):
		frappe.db.set_value("Indeed Application", application_id, "error", truncate(error))
		return
	record.status = "Failed"
	record.error = truncate(error)
	try:
		record.insert(ignore_permissions=True, ignore_if_duplicate=True)
	except Exception:
		frappe.log_error(
			title=f"Indeed: could not persist failed application {application_id}",
			message=frappe.get_traceback(),
		)


def fetch_application(application_id):
	settings = get_settings()
	client = IndeedClient(settings)
	data = client.execute(
		get_operation(settings, "application_query", DEFAULT_APPLICATION_QUERY),
		{"id": application_id},
		operation="application_get",
		reference_doctype="Indeed Application",
		reference_name=application_id,
	)
	return find_first_key(data, "jobApplication") or data


def sync_applications():
	if not is_enabled("enable_application_sync"):
		return

	settings = get_settings()
	max_pages = 5
	rows = frappe.get_all(
		"Indeed Job Sync",
		filters={"status": "Synced", "indeed_job_id": ["is", "set"]},
		fields=["name", "job_key", "application_cursor"],
		limit=50,
	)

	client = IndeedClient(settings)
	for row in rows:
		job_key = row.job_key
		cursor = row.application_cursor
		for _page in range(max_pages):
			try:
				data = client.execute(
					get_operation(settings, "applications_query", DEFAULT_APPLICATIONS_QUERY),
					{"jobKey": job_key, "cursor": cursor, "first": 50},
					operation="applications_list",
					reference_doctype="Indeed Job Sync",
					reference_name=row.name,
				)
			except IndeedError:
				break

			nodes = find_first_key(data, "nodes") or []
			if not isinstance(nodes, list):
				break
			for node in nodes:
				if isinstance(node, dict):
					process_application(node)

			page_info = find_first_key(data, "pageInfo") or {}
			if not isinstance(page_info, dict):
				break
			next_cursor = page_info.get("endCursor")
			if next_cursor:
				cursor = next_cursor
				frappe.db.set_value(
					"Indeed Job Sync", row.name, "application_cursor", cursor, update_modified=False
				)
			if not page_info.get("hasNextPage"):
				break
			if not next_cursor:
				log_sync(
					"Failed",
					operation="applications_list",
					error=_("Pagination cursor missing while hasNextPage is true"),
					reference_doctype="Indeed Job Sync",
					reference_name=row.name,
				)
				break


def application_count(job_opening):
	return cint(frappe.db.count("Indeed Application", {"job_opening": job_opening, "status": "Linked"}))
