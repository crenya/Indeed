import unittest

from frappe.tests.utils import FrappeTestCase

from indeed.utils import (
	deep_pick,
	extract_job_id,
	find_first_key,
	sign_payload,
	verify_signature,
)


class TestIndeedUtils(FrappeTestCase):
	def test_verify_signature_accepts_prefixed_digest(self):
		body = b'{"hello":"world"}'
		secret = "topsecret"
		signature = "sha256=" + sign_payload(secret, body)

		self.assertTrue(verify_signature(secret, body, signature))

	def test_verify_signature_rejects_tampered_body(self):
		secret = "topsecret"
		signature = sign_payload(secret, b'{"a":1}')

		self.assertFalse(verify_signature(secret, b'{"a":2}', signature))

	def test_verify_signature_rejects_missing_values(self):
		self.assertFalse(verify_signature("", b"{}", "abc"))
		self.assertFalse(verify_signature("secret", b"{}", ""))

	def test_verify_signature_accepts_uppercase_header_prefix(self):
		body = b"payload"
		signature = "SHA256=" + sign_payload("secret", body)

		self.assertTrue(verify_signature("secret", body, signature))

	def test_deep_pick(self):
		payload = {"candidate": {"email": "a@b.com", "name": "Ada"}}

		self.assertEqual(deep_pick(payload, "candidate.email", "email"), "a@b.com")
		self.assertEqual(deep_pick(payload, "missing.value", "candidate.name"), "Ada")
		self.assertIsNone(deep_pick(payload, "missing.value"))

	def test_find_first_key(self):
		payload = {"data": {"list": [{"jobPosting": {"id": "abc"}}]}}

		self.assertEqual(find_first_key(payload, "jobPosting"), {"id": "abc"})

	def test_extract_job_id_prefers_posting(self):
		payload = {"jobPostingCreate": {"jobPosting": {"id": "indeed-1", "jobKey": "JO-1"}}}

		self.assertEqual(extract_job_id(payload), "indeed-1")

	def test_extract_job_id_falls_back_to_posting_id(self):
		payload = {"jobPostingCreate": {"jobPostingId": "indeed-2"}}

		self.assertEqual(extract_job_id(payload), "indeed-2")

	def test_extract_job_id_returns_none(self):
		self.assertIsNone(extract_job_id({"jobPostingCreate": {"ok": True}}))


if __name__ == "__main__":
	unittest.main()
