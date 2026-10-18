import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from indeed.applications import extract_applications
from indeed.payload import build_job_payload


def make_settings(**overrides):
	values = {
		"job_country": "in",
		"default_apply_url": None,
		"default_company_name": "Acme",
		"auto_publish_new_jobs": 1,
	}
	values.update(overrides)
	return frappe._dict(values)


class TestPayload(FrappeTestCase):
	@patch("indeed.payload.get_settings")
	def test_build_job_payload(self, get_settings):
		get_settings.return_value = make_settings()
		opening = frappe_dict(
			name="HR-OPN-0001",
			job_title="Backend Engineer",
			company=None,
			route="jobs/acme/backend-engineer",
			description="<p>Build things</p>",
			employment_type="Full Time",
			closes_on=None,
			location="Kochi",
			publish_salary_range=1,
			lower_range=500000,
			upper_range=900000,
			currency="INR",
			salary_per="Year",
			indeed_job_key=None,
		)

		payload = build_job_payload(opening)

		self.assertEqual(payload["jobKey"], "HR-OPN-0001")
		self.assertEqual(payload["jobReferenceNumber"], "HR-OPN-0001")
		self.assertEqual(payload["title"], "Backend Engineer")
		self.assertEqual(payload["companyName"], "Acme")
		self.assertEqual(payload["location"], {"country": "IN", "city": "Kochi"})
		self.assertEqual(payload["employmentType"], ["FULL_TIME"])
		self.assertEqual(
			payload["salary"],
			{"minimum": 500000.0, "maximum": 900000.0, "currency": "INR", "unit": "YEAR"},
		)
		self.assertNotIn("expirationDate", payload)

	@patch("indeed.payload.get_settings")
	def test_salary_omitted_when_not_published(self, get_settings):
		get_settings.return_value = make_settings(default_apply_url="https://example.com/apply")
		opening = frappe_dict(
			name="HR-OPN-0002",
			job_title="Designer",
			company=None,
			route=None,
			description=None,
			employment_type="Contract",
			closes_on=None,
			location=None,
			publish_salary_range=0,
			lower_range=0,
			upper_range=0,
			currency=None,
			salary_per=None,
			indeed_job_key=None,
		)

		payload = build_job_payload(opening)

		self.assertNotIn("salary", payload)
		self.assertEqual(payload["applyUrl"], "https://example.com/apply")
		self.assertEqual(payload["employmentType"], ["CONTRACTOR"])


class TestExtractApplications(FrappeTestCase):
	def test_list_payload(self):
		self.assertEqual(len(extract_applications([{"id": "1"}, {"id": "2"}])), 2)

	def test_applications_key(self):
		self.assertEqual(extract_applications({"applications": [{"id": "1"}]}), [{"id": "1"}])

	def test_events_key(self):
		payload = {"events": [{"data": {"id": "1", "candidate": {"name": "A"}}}]}

		self.assertEqual(extract_applications(payload), [{"id": "1", "candidate": {"name": "A"}}])

	def test_single_application_payload(self):
		payload = {"id": "abc", "jobKey": "JO-1", "candidate": {"email": "a@b.com"}}

		self.assertEqual(extract_applications(payload), [payload])

	def test_empty_payload(self):
		self.assertEqual(extract_applications({}), [])


def frappe_dict(**kwargs):
	class Row(dict):
		def get(self, key, default=None):
			return super().get(key, default)

		def __getattr__(self, key):
			try:
				return self[key]
			except KeyError:
				raise AttributeError(key)

	return Row(kwargs)


if __name__ == "__main__":
	unittest.main()
