from typing import Optional

import frappe
from frappe import _

from indeed.applications import fetch_application, process_application
from indeed.applications import sync_applications as sync_apps
from indeed.client import IndeedClient
from indeed.jobs import enqueue_sync, queue_sync
from indeed.utils import (
	get_settings,
	is_enabled,
	log_sync,
	verify_signature,
)


@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep: guest-whitelisted-method
def webhook():
	"""Inbound application webhook from Indeed.

	Guest-allowed by design: Indeed cannot authenticate as a site user. Requests are rejected
	unless Indeed Settings is enabled and the HMAC-SHA256 signature over the raw body matches
	the configured webhook secret (see `verify_signature`).
	"""
	settings = get_settings()

	if not settings.enabled or not settings.enable_application_sync:
		frappe.throw(_("Indeed application sync is disabled"), frappe.PermissionError)

	secret = settings.get_password("webhook_secret", raise_exception=False)
	if not secret:
		frappe.throw(_("Webhook secret is not configured in Indeed Settings"), frappe.PermissionError)

	raw = frappe.request.get_data() or b""
	header_name = settings.webhook_signature_header or "X-Indeed-Signature"
	signature = frappe.get_request_header(header_name) or ""

	if not verify_signature(secret, raw, signature):
		log_sync(
			"Failed",
			direction="Inbound",
			operation="webhook",
			request_body=raw.decode("utf-8", errors="replace") if raw else None,
			error=_("Invalid or missing signature"),
		)
		frappe.throw(_("Invalid signature"), frappe.AuthenticationError)

	try:
		payload = frappe.parse_json(raw.decode("utf-8")) if raw else {}
	except ValueError:
		frappe.throw(_("Invalid JSON payload"), frappe.ValidationError)

	log_sync(
		"Success",
		direction="Inbound",
		operation="webhook",
		request_body=payload,
	)

	frappe.enqueue(
		"indeed.applications.handle_webhook",
		queue="short",
		timeout=600,
		payload=payload,
	)

	return {"status": "accepted"}


@frappe.whitelist()
def test_connection():
	client = IndeedClient()
	data = client.execute("query Ping { __typename }", {}, operation="test_connection")
	return {"ok": True, "data": data}


@frappe.whitelist()
def publish_now(job_opening: str, expire: Optional[int] = None):
	frappe.has_permission("Job Opening", "write", doc=job_opening, throw=True)
	if not is_enabled("enable_job_publishing"):
		frappe.throw(_("Indeed job publishing is disabled in Indeed Settings"))

	action = "Expire" if frappe.utils.cint(expire) else None
	queue_sync(job_opening, action)
	return {"queued": True}


@frappe.whitelist()
def retry_now(job_sync: str):
	frappe.has_permission("Indeed Job Sync", "write", throw=True)
	enqueue_sync(job_sync)
	return {"queued": True}


@frappe.whitelist()
def sync_applications_now():
	frappe.only_for(("System Manager", "HR Manager"))
	sync_apps()
	return {"ok": True}


@frappe.whitelist()
def sync_status(job_opening: str):
	row = frappe.db.get_value(
		"Indeed Job Sync",
		job_opening,
		["status", "desired_action", "indeed_job_id", "job_key", "last_error", "attempt_count"],
		as_dict=True,
	)
	return row or {}


@frappe.whitelist()
def fetch_application_now(application_id: str):
	frappe.only_for(("System Manager", "HR Manager"))
	payload = fetch_application(application_id)
	return process_application(payload) if isinstance(payload, dict) else payload
