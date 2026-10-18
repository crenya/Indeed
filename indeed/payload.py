import frappe
from frappe.utils import flt, get_url

from indeed.utils import get_settings

EMPLOYMENT_TYPE_MAP = (
	("full", "FULL_TIME"),
	("part", "PART_TIME"),
	("intern", "INTERN"),
	("contract", "CONTRACTOR"),
	("freelance", "CONTRACTOR"),
	("tempor", "TEMPORARY"),
	("seasonal", "TEMPORARY"),
	("volunt", "VOLUNTEER"),
	("per diem", "PER_DIEM"),
)

SALARY_UNIT_MAP = {
	"hour": "HOUR",
	"hourly": "HOUR",
	"day": "DAY",
	"daily": "DAY",
	"week": "WEEK",
	"weekly": "WEEK",
	"month": "MONTH",
	"monthly": "MONTH",
	"year": "YEAR",
	"yearly": "YEAR",
	"annual": "YEAR",
}


def get_job_key(doc):
	return doc.get("indeed_job_key") or doc.name


def get_company_name(doc):
	settings = get_settings()
	return (
		frappe.db.get_value("Company", doc.get("company"), "company_name")
		or settings.default_company_name
		or doc.get("company")
		or ""
	)


def get_apply_url(doc):
	settings = get_settings()
	if settings.default_apply_url:
		return settings.default_apply_url
	route = doc.get("route")
	if not route:
		company = frappe.scrub(doc.get("company") or "")
		title = frappe.scrub(doc.get("job_title") or "").replace("_", "-")
		route = f"jobs/{company}/{title}"
	route = str(route).strip("/")
	return get_url(f"/{route}")


def get_employment_types(doc):
	value = (doc.get("employment_type") or "").strip().lower()
	if not value:
		return []
	for needle, mapped in EMPLOYMENT_TYPE_MAP:
		if needle in value:
			return [mapped]
	return ["OTHER"]


def get_salary_unit(doc):
	value = (doc.get("salary_per") or "Year").strip().lower()
	return SALARY_UNIT_MAP.get(value, "YEAR")


def build_salary(doc):
	if not doc.get("publish_salary_range"):
		return None
	minimum = flt(doc.get("lower_range"))
	maximum = flt(doc.get("upper_range"))
	if not (minimum or maximum):
		return None
	return {
		"minimum": minimum or None,
		"maximum": maximum or None,
		"currency": doc.get("currency") or None,
		"unit": get_salary_unit(doc),
	}


def build_location(doc):
	settings = get_settings()
	location = {"country": (settings.job_country or "").upper() or None}
	name = (doc.get("location") or "").strip()
	if name:
		location["city"] = name
	return location


def build_job_payload(doc):
	payload = {
		"jobKey": get_job_key(doc),
		"jobReferenceNumber": doc.name,
		"title": doc.get("job_title"),
		"description": doc.get("description"),
		"companyName": get_company_name(doc),
		"applyUrl": get_apply_url(doc),
		"sourceName": "ERPNext",
		"location": build_location(doc),
		"employmentType": get_employment_types(doc),
		"expirationDate": str(doc.get("closes_on")) if doc.get("closes_on") else None,
		"salary": build_salary(doc),
	}
	return strip_empty(payload)


def strip_empty(value):
	if isinstance(value, dict):
		cleaned = {}
		for key, item in value.items():
			item = strip_empty(item)
			if item not in (None, "", [], {}):
				cleaned[key] = item
		return cleaned
	if isinstance(value, list):
		return [strip_empty(item) for item in value if item not in (None, "", [], {})]
	return value
