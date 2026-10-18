import time

import frappe
import requests
from frappe import _
from frappe.utils import cint

from indeed.utils import (
	get_settings,
	log_sync,
	render_error,
)


class IndeedError(frappe.ValidationError):
	pass


class IndeedClient:
	"""Thin Indeed GraphQL client with OAuth2 client-credentials, retries and logging."""

	max_attempts = 3

	def __init__(self, settings=None):
		self.settings = settings or get_settings()

	def validate_configuration(self):
		missing = [
			label
			for field, label in (
				("client_id", _("Client ID")),
				("client_secret", _("Client Secret")),
				("token_endpoint", _("Token Endpoint")),
				("graphql_endpoint", _("GraphQL Endpoint")),
			)
			if not self.settings.get(field)
		]
		if missing:
			frappe.throw(
				_("Indeed Settings is incomplete. Missing: {0}").format(", ".join(missing)),
				title=_("Indeed Configuration"),
			)

	def _timeout(self):
		return cint(self.settings.request_timeout) or 30

	def _token_cache_key(self):
		return f"indeed:access_token:{self.settings.client_id}"

	def get_access_token(self, force=False):
		if not force:
			token = frappe.cache.get_value(self._token_cache_key())
			if token:
				return token

		self.validate_configuration()
		try:
			response = requests.post(
				self.settings.token_endpoint,
				data={
					"grant_type": "client_credentials",
					"client_id": self.settings.client_id,
					"client_secret": self.settings.get_password("client_secret"),
					"scope": self.settings.scope or "employer_access",
				},
				headers={"Accept": "application/json"},
				timeout=self._timeout(),
			)
		except requests.RequestException as exc:
			log_sync("Failed", operation="token", error=str(exc))
			raise IndeedError(render_error(_("Could not reach the token endpoint: {0}").format(str(exc))))

		if response.status_code >= 400:
			log_sync(
				"Failed",
				operation="token",
				http_status=response.status_code,
				response_body=response.text,
				error=_("Token request rejected"),
			)
			raise IndeedError(
				render_error(_("Token request failed with HTTP {0}").format(response.status_code))
			)

		try:
			data = response.json()
		except ValueError:
			raise IndeedError(render_error(_("Token endpoint returned invalid JSON")))

		token = data.get("access_token")
		if not token:
			log_sync("Failed", operation="token", response_body=data, error=_("No access_token in response"))
			raise IndeedError(render_error(_("Token endpoint did not return an access_token")))

		expires_in = cint(data.get("expires_in")) or 3600
		frappe.cache.set_value(self._token_cache_key(), token, expires_in_sec=max(60, expires_in - 300))
		return token

	def execute(
		self,
		query,
		variables=None,
		operation=None,
		reference_doctype=None,
		reference_name=None,
	):
		self.validate_configuration()
		variables = variables or {}
		request_body = {"query": query, "variables": variables}
		token = self.get_access_token()
		last_error = None
		last_response = None

		for attempt in range(1, self.max_attempts + 1):
			started = time.monotonic()
			try:
				response = requests.post(
					self.settings.graphql_endpoint,
					json={"query": query, "variables": variables},
					headers={
						"Authorization": f"Bearer {token}",
						"Content-Type": "application/json",
						"Accept": "application/json",
					},
					timeout=self._timeout(),
				)
			except requests.RequestException as exc:
				last_error = str(exc)
				last_response = None
				if attempt < self.max_attempts:
					time.sleep(min(2**attempt, 10))
					continue
				duration = int((time.monotonic() - started) * 1000)
				log_sync(
					"Failed",
					operation=operation,
					request_body=request_body,
					error=last_error,
					duration_ms=duration,
					attempts=attempt,
					reference_doctype=reference_doctype,
					reference_name=reference_name,
				)
				raise IndeedError(render_error(_("Could not reach Indeed: {0}").format(str(exc))))

			duration = int((time.monotonic() - started) * 1000)
			last_response = response

			if response.status_code == 401 and attempt == 1:
				token = self.get_access_token(force=True)
				continue

			if response.status_code == 429 or response.status_code >= 500:
				last_error = _("HTTP {0}").format(response.status_code)
				if attempt < self.max_attempts:
					retry_after = cint(response.headers.get("Retry-After"))
					time.sleep(retry_after or min(2**attempt, 10))
					continue
				log_sync(
					"Failed",
					operation=operation,
					request_body=request_body,
					response_body=response.text,
					http_status=response.status_code,
					duration_ms=duration,
					attempts=attempt,
					error=last_error,
					reference_doctype=reference_doctype,
					reference_name=reference_name,
				)
				raise IndeedError(render_error(last_error))

			try:
				data = response.json()
			except ValueError:
				data = {"raw": response.text}

			errors = data.get("errors") if isinstance(data, dict) else None
			if response.status_code >= 400 or errors:
				message = _format_errors(errors) or _("HTTP {0}").format(response.status_code)
				log_sync(
					"Failed",
					operation=operation,
					request_body=request_body,
					response_body=data,
					http_status=response.status_code,
					duration_ms=duration,
					attempts=attempt,
					error=message,
					reference_doctype=reference_doctype,
					reference_name=reference_name,
				)
				raise IndeedError(render_error(message))

			log_sync(
				"Success",
				operation=operation,
				request_body=request_body,
				response_body=data,
				http_status=response.status_code,
				duration_ms=duration,
				attempts=attempt,
				reference_doctype=reference_doctype,
				reference_name=reference_name,
			)
			return data.get("data") if isinstance(data, dict) else data

		# Exhausted retries on 429/5xx
		message = last_error or _("Request failed after retries")
		log_sync(
			"Failed",
			operation=operation,
			request_body=request_body,
			response_body=last_response.text if last_response is not None else None,
			http_status=last_response.status_code if last_response is not None else None,
			attempts=self.max_attempts,
			error=message,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
		)
		raise IndeedError(render_error(message))


def _format_errors(errors):
	if not errors:
		return None
	if isinstance(errors, dict):
		errors = [errors]
	messages = []
	for error in errors:
		if isinstance(error, dict):
			messages.append(error.get("message") or frappe.as_json(error))
		else:
			messages.append(str(error))
	return "; ".join(messages)
