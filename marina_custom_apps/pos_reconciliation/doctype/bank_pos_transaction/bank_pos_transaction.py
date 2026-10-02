from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

KEY_SEPARATOR = "|"

TRANSACTION_TYPE_ALIASES = {
    "PUR": "PURCHASE",
    "PURCHASE": "PURCHASE",
    "REF": "REFUND",
    "REFUND": "REFUND",
    "RETURN": "REFUND",
}

IMMUTABLE_SOURCE_FIELDS = (
    "site_id",
    "terminal_id",
    "rrn",
    "auth_code",
    "transaction_type",
    "card_type",
    "masked_card_number",
    "transaction_date",
    "transaction_time",
    "transaction_amount",
)


def clean_text(value) -> str:
    return str(value or "").strip()


def normalize_transaction_type(value) -> str:
    normalized = clean_text(value).upper().replace(" ", "_")
    return TRANSACTION_TYPE_ALIASES.get(normalized, normalized)


def build_reconciliation_key(terminal_id, rrn, auth_code, transaction_type) -> str:
    parts = (
        clean_text(terminal_id),
        clean_text(rrn),
        clean_text(auth_code),
        normalize_transaction_type(transaction_type),
    )

    if any(not part for part in parts):
        frappe.throw(
            _("Terminal ID, RRN, Auth Code and Transaction Type are required to build the reconciliation key.")
        )

    if any(KEY_SEPARATOR in part for part in parts):
        frappe.throw(_("Reconciliation key fields cannot contain the character {0}.").format(KEY_SEPARATOR))

    return KEY_SEPARATOR.join(parts)


class BankPOSTransaction(Document):
    def validate(self):
        self._normalize_source_values()
        self.reconciliation_key = build_reconciliation_key(
            self.terminal_id,
            self.rrn,
            self.auth_code,
            self.transaction_type,
        )
        self._protect_source_identity()

    def _normalize_source_values(self):
        self.bank_mid = clean_text(self.bank_mid)
        self.site_id = clean_text(self.site_id)
        self.terminal_id = clean_text(self.terminal_id)
        self.rrn = clean_text(self.rrn)
        self.auth_code = clean_text(self.auth_code)
        self.transaction_type = normalize_transaction_type(self.transaction_type)
        self.card_type = clean_text(self.card_type).upper()
        self.masked_card_number = clean_text(self.masked_card_number)
        self.transaction_status = clean_text(self.transaction_status)
        self.rejection_reason = clean_text(self.rejection_reason)
        self.settlement_number = clean_text(self.settlement_number)
        self.pos_reconciliation_number = clean_text(self.pos_reconciliation_number)

    def _protect_source_identity(self):
        previous = self.get_doc_before_save()
        if not previous:
            return

        changed = []
        for fieldname in IMMUTABLE_SOURCE_FIELDS:
            if previous.get(fieldname) != self.get(fieldname):
                changed.append(self.meta.get_label(fieldname) or fieldname)

        if changed:
            frappe.throw(
                _("Bank source identity fields cannot be changed after import: {0}").format(
                    ", ".join(changed)
                )
            )
