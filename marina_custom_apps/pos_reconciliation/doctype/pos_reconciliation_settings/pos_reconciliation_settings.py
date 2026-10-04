from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from marina_custom_apps.pos_reconciliation.card_type_mapping import normalize_card_type_token


class POSReconciliationSettings(Document):
    def validate(self):
        self._validate_card_type_mappings()
        if self.enable_accounting_posting:
            from marina_custom_apps.pos_reconciliation.accounting_service import validate_accounting_settings
            validate_accounting_settings(self)

    def _validate_card_type_mappings(self):
        bank_seen = {}
        alhamrani_seen = {}
        for row in self.get("card_type_mappings") or []:
            unified = normalize_card_type_token(row.unified_card_type)
            bank = normalize_card_type_token(row.bank_card_type)
            alhamrani = normalize_card_type_token(row.alhamrani_card_type)
            if not unified:
                frappe.throw(_("Unified Card Type is required in row {0}.").format(row.idx))
            if not bank and not alhamrani:
                frappe.throw(_("Bank Card Type or Alhamrani Card Type is required in row {0}.").format(row.idx))
            self._check_conflict(bank_seen, bank, unified, "Bank")
            self._check_conflict(alhamrani_seen, alhamrani, unified, "Alhamrani")

    @staticmethod
    def _check_conflict(seen, source_value, unified, source_name):
        if not source_value:
            return
        previous = seen.get(source_value)
        if previous and previous != unified:
            frappe.throw(_("{0} card type {1} is mapped to both {2} and {3}.").format(source_name, source_value, previous, unified))
        seen[source_value] = unified