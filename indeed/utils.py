import hashlib
import hmac
import json

import frappe
from frappe import _
from frappe.utils import cint

DEFAULT_GRAPHQL_ENDPOINT = "https://apis.indeed.com/graphql"
DEFAULT_TOKEN_ENDPOINT = "https://apis.indeed.com/oauth/v2/tokens"
DEFAULT_SCOPE = "employer_access"

DEFAULT_JOB_CREATE_MUTATION = """mutation PublishJob($input: JobPostingInput!) {
	jobPostingCreate(input: $input) {
		jobPosting {
			id
			jobKey
		}
	}
}"""

DEFAULT_JOB_UPDATE_MUTATION = """mutation UpdateJob($input: JobPostingInput!) {
	jobPostingUpdate(input: $input) {
		jobPosting {
			id
			jobKey
		}
	}
}"""

DEFAULT_JOB_EXPIRE_MUTATION = """mutation ExpireJob($jobKey: ID!, $jobPostingId: ID) {
	jobPostingExpire(jobKey: $jobKey, jobPostingId: $jobPostingId) {
		jobPosting {
			id
			jobKey
		}
	}
}"""

DEFAULT_APPLICATION_QUERY = """query Application($id: ID!) {
	jobApplication(id: $id) {
		id
		jobKey
		status
		appliedAt
		resumeUrl
		coverLetter
		candidate {
			id
			name
			email
			phone
		}
	}
}"""

DEFAULT_APPLICATIONS_QUERY = """query Applications($jobKey: ID!, $cursor: String, $first: Int) {
	jobApplications(jobKey: $jobKey, after: $cursor, first: $first) {
		nodes {
			id
			jobKey
			status
			appliedAt
			resumeUrl
			coverLetter
			candidate {
				id
				name
				email
				phone
			}
		}
		pageInfo {
			endCursor
			hasNextPage
		}
	}
}"""


def get_settings():
	return frappe.get_cached_doc("Indeed Settings")


def is_enabled(feature=None):
	settings = get_settings()
	if not cint(settings.enabled):
		return False
	if feature and not cint(settings.get(feature)):
		return False
	return True


def get_operation(settings, field, default):
	value = (settings.get(field) or "").strip()
	return value or default


def payload_hash(payload):
	return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def truncate(value, limit=None):
	if value is None:
		return None
	limit = cint(limit) or cint(get_settings().max_log_body_chars) or 20000
	if not isinstance(value, str):
		value = frappe.as_json(value, indent=1)
	if len(value) <= limit:
		return value
	return value[:limit] + "\n... [truncated]"


def log_sync(
	status,
	direction="Outbound",
	operation=None,
	request_body=None,
	response_body=None,
	http_status=None,
	duration_ms=None,
	attempts=1,
	error=None,
	reference_doctype=None,
	reference_name=None,
	correlation_id=None,
):
	try:
		log = frappe.get_doc(
			{
				"doctype": "Indeed Sync Log",
				"status": status,
				"direction": direction,
				"operation": operation,
				"request_body": truncate(request_body),
				"response_body": truncate(response_body),
				"http_status": http_status,
				"duration_ms": duration_ms,
				"attempts": attempts,
				"error": truncate(error),
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"correlation_id": correlation_id,
			}
		)
		log.insert(ignore_permissions=True)
		return log.name
	except Exception:
		frappe.log_error(title="Indeed: failed to write sync log")
		return None


def deep_pick(data, *paths):
	for path in paths:
		node = data
		for part in path.split("."):
			if isinstance(node, dict) and part in node:
				node = node[part]
			elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
				node = node[int(part)]
			else:
				node = None
				break
		if node not in (None, "", [], {}):
			return node
	return None


def find_first_key(data, key):
	if isinstance(data, dict):
		if key in data and data[key] not in (None, "", [], {}):
			return data[key]
		for value in data.values():
			found = find_first_key(value, key)
			if found not in (None, "", [], {}):
				return found
	elif isinstance(data, list):
		for item in data:
			found = find_first_key(item, key)
			if found not in (None, "", [], {}):
				return found
	return None


def extract_job_id(data):
	posting = find_first_key(data, "jobPosting")
	if isinstance(posting, dict):
		for key in ("id", "jobPostingId"):
			if posting.get(key):
				return posting[key]
	for key in ("jobPostingId", "jobId"):
		value = find_first_key(data, key)
		if value:
			return value
	return None


def sign_payload(secret, body):
	if isinstance(body, str):
		body = body.encode("utf-8")
	return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_signature(secret, body, signature):
	if not secret or not signature:
		return False
	if isinstance(body, str):
		body = body.encode("utf-8")
	expected = sign_payload(secret, body)
	signature = signature.strip()
	for prefix in ("sha256=", "SHA256="):
		if signature.startswith(prefix):
			signature = signature[len(prefix) :]
	return hmac.compare_digest(expected, signature.lower())


def render_error(message):
	return _("Indeed API error: {0}").format(message)
