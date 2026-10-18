import frappe

CUSTOM_FIELDS = {
	"Job Opening": [
		{
			"fieldname": "indeed_section",
			"label": "Indeed",
			"fieldtype": "Section Break",
			"insert_after": "publish_applications_received",
			"collapsible": 1,
		},
		{
			"fieldname": "publish_to_indeed",
			"label": "Publish to Indeed",
			"fieldtype": "Check",
			"insert_after": "indeed_section",
			"default": "0",
			"description": "Also published automatically when Auto Publish New Jobs is enabled in Indeed Settings.",
		},
		{
			"fieldname": "indeed_job_key",
			"label": "Indeed Job Key",
			"fieldtype": "Data",
			"insert_after": "publish_to_indeed",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"fieldname": "indeed_job_id",
			"label": "Indeed Job ID",
			"fieldtype": "Data",
			"insert_after": "indeed_job_key",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"fieldname": "indeed_sync_status",
			"label": "Indeed Sync Status",
			"fieldtype": "Data",
			"insert_after": "indeed_job_id",
			"read_only": 1,
			"in_list_view": 1,
			"in_standard_filter": 1,
		},
		{
			"fieldname": "indeed_last_synced_on",
			"label": "Indeed Last Synced On",
			"fieldtype": "Datetime",
			"insert_after": "indeed_sync_status",
			"read_only": 1,
		},
	],
	"Job Applicant": [
		{
			"fieldname": "indeed_section",
			"label": "Indeed",
			"fieldtype": "Section Break",
			"insert_after": "notes",
			"collapsible": 1,
		},
		{
			"fieldname": "from_indeed",
			"label": "Received from Indeed",
			"fieldtype": "Check",
			"insert_after": "indeed_section",
			"read_only": 1,
			"default": "0",
		},
		{
			"fieldname": "indeed_application_id",
			"label": "Indeed Application ID",
			"fieldtype": "Data",
			"insert_after": "from_indeed",
			"read_only": 1,
			"no_copy": 1,
			"unique": 1,
		},
		{
			"fieldname": "indeed_candidate_id",
			"label": "Indeed Candidate ID",
			"fieldtype": "Data",
			"insert_after": "indeed_application_id",
			"read_only": 1,
			"no_copy": 1,
		},
	],
}


def sync_custom_fields():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	for doctype, fields in CUSTOM_FIELDS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		for definition in fields:
			name = f"{doctype}-{definition['fieldname']}"
			if frappe.db.exists("Custom Field", name):
				existing = frappe.get_doc("Custom Field", name)
				changed = False
				for key, value in definition.items():
					if existing.get(key) != value:
						existing.set(key, value)
						changed = True
				if changed:
					existing.save(ignore_permissions=True)
			else:
				create_custom_field(doctype, definition)
		frappe.clear_cache(doctype=doctype)
