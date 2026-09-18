import frappe
from frappe.tests import IntegrationTestCase

from marina_custom_apps.permission_manager.api.permissions import RIGHTS, _normalize_rights


class TestPermissionNormalization(IntegrationTestCase):
	def test_higher_permission_levels_only_keep_read_and_write(self):
		meta = frappe._dict(is_submittable=1, issingle=0, allow_import=1)
		rights = {right: 1 for right in RIGHTS}

		normalized = _normalize_rights(meta, permlevel=1, if_owner=0, rights=rights)

		self.assertEqual(normalized["read"], 1)
		self.assertEqual(normalized["write"], 1)
		self.assertTrue(all(not normalized[right] for right in RIGHTS if right not in ("read", "write")))

	def test_doctype_capabilities_disable_inapplicable_rights(self):
		meta = frappe._dict(is_submittable=0, issingle=1, allow_import=0)
		rights = {right: 1 for right in RIGHTS}

		normalized = _normalize_rights(meta, permlevel=0, if_owner=1, rights=rights)

		for right in ("submit", "cancel", "amend", "report", "import", "export"):
			self.assertEqual(normalized[right], 0)
