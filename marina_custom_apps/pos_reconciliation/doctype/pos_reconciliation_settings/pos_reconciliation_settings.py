from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class POSReconciliationSettings(Document):
    def validate(self):
        self._validate_profile_mappings()

    def _validate_profile_mappings(self):
        seen = set()
        for row in self.get("profile_mappings") or []:
            if not row.pos_profile:
                continue
            if row.pos_profile in seen:
                frappe.throw(
                    _("POS Profile {0} appears more than once in accounting mapping.").format(
                        frappe.bold(row.pos_profile)
                    )
                )
            seen.add(row.pos_profile)
