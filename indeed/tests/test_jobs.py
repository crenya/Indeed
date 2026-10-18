import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from indeed.jobs import desired_action


class TestDesiredAction(FrappeTestCase):
	@patch("indeed.jobs.frappe.db.get_value")
	@patch("indeed.jobs.get_settings")
	def test_publish_when_not_yet_posted(self, get_settings, get_value):
		get_settings.return_value = frappe._dict({"auto_publish_new_jobs": 1})
		get_value.return_value = None
		opening = type(
			"Opening",
			(),
			{
				"name": "HR-OPN-0001",
				"get": lambda self, key, default=None: {"status": "Open", "publish_to_indeed": 0}.get(
					key, default
				),
			},
		)()

		self.assertEqual(desired_action(opening), "Publish")

	@patch("indeed.jobs.frappe.db.get_value")
	@patch("indeed.jobs.get_settings")
	def test_update_when_already_posted(self, get_settings, get_value):
		get_settings.return_value = frappe._dict({"auto_publish_new_jobs": 1})
		get_value.return_value = "indeed-1"
		opening = type(
			"Opening",
			(),
			{
				"name": "HR-OPN-0001",
				"get": lambda self, key, default=None: {"status": "Open", "publish_to_indeed": 0}.get(
					key, default
				),
			},
		)()

		self.assertEqual(desired_action(opening), "Update")

	@patch("indeed.jobs.frappe.db.get_value")
	@patch("indeed.jobs.get_settings")
	def test_expire_when_closed(self, get_settings, get_value):
		get_settings.return_value = frappe._dict({"auto_publish_new_jobs": 1})
		get_value.return_value = "indeed-1"
		opening = type(
			"Opening",
			(),
			{
				"name": "HR-OPN-0001",
				"get": lambda self, key, default=None: {"status": "Closed", "publish_to_indeed": 1}.get(
					key, default
				),
			},
		)()

		self.assertEqual(desired_action(opening), "Expire")

	@patch("indeed.jobs.frappe.db.get_value")
	@patch("indeed.jobs.get_settings")
	def test_none_when_opt_out_and_auto_disabled(self, get_settings, get_value):
		get_settings.return_value = frappe._dict({"auto_publish_new_jobs": 0})
		get_value.return_value = None
		opening = type(
			"Opening",
			(),
			{
				"name": "HR-OPN-0001",
				"get": lambda self, key, default=None: {"status": "Open", "publish_to_indeed": 0}.get(
					key, default
				),
			},
		)()

		self.assertIsNone(desired_action(opening))


if __name__ == "__main__":
	unittest.main()
