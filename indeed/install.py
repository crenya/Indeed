import frappe

from indeed.setup import sync_custom_fields


def after_install():
	sync_custom_fields()


def after_migrate():
	sync_custom_fields()


def before_tests():
	from frappe.test_runner import make_test_records

	make_test_records("Job Opening")
