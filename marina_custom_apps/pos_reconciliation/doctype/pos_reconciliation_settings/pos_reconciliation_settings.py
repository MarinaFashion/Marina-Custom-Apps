from __future__ import annotations

from frappe.model.document import Document


class POSReconciliationSettings(Document):
    def validate(self):
        if not self.enable_accounting_posting:
            return

        from marina_custom_apps.pos_reconciliation.accounting_service import validate_accounting_settings

        validate_accounting_settings(self)
