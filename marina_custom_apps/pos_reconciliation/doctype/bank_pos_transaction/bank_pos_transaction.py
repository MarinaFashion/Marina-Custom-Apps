from __future__ import annotations

from datetime import datetime

import frappe
from frappe import _
from frappe.model.document import Document

from marina_custom_apps.pos_reconciliation.location_service import resolve_pos_profile

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


def normalize_bank_date(value):
    """Accept compact bank YYYYMMDD values while preserving ERP Date fields."""
    if value in (None, ""):
        return None
    if hasattr(value, "strftime") and not isinstance(value, str):
        return value
    text = clean_text(value)
    if len(text) == 8 and text.isdigit():
        try:
            return datetime.strptime(text, "%Y%m%d").date()
        except ValueError:
            return value
    return value


def try_build_reconciliation_key(terminal_id, rrn, auth_code, transaction_type):
    parts = (
        clean_text(terminal_id),
        clean_text(rrn),
        clean_text(auth_code),
        normalize_transaction_type(transaction_type),
    )
    labels = ("Terminal ID", "RRN", "Auth Code", "Transaction Type")

    missing = [label for label, part in zip(labels, parts) if not part]
    if missing:
        return None, _("Incomplete reconciliation key: missing {0}.").format(", ".join(missing))

    if any(KEY_SEPARATOR in part for part in parts):
        return None, _("Reconciliation key fields cannot contain the character {0}.").format(KEY_SEPARATOR)

    return KEY_SEPARATOR.join(parts), None


def build_reconciliation_key(terminal_id, rrn, auth_code, transaction_type) -> str:
    key, error = try_build_reconciliation_key(terminal_id, rrn, auth_code, transaction_type)
    if error:
        frappe.throw(error)
    return key


class BankPOSTransaction(Document):
    def validate(self):
        self._normalize_source_values()
        self.reconciliation_key = build_reconciliation_key(
            self.terminal_id,
            self.rrn,
            self.auth_code,
            self.transaction_type,
        )
        self._assign_pos_profile_on_insert()
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
        self.transaction_date = normalize_bank_date(self.transaction_date)
        self.balance_date = normalize_bank_date(self.balance_date)
        self.settlement_date = normalize_bank_date(self.settlement_date)
        self.settlement_number = clean_text(self.settlement_number)
        self.pos_reconciliation_number = clean_text(self.pos_reconciliation_number)

    def _assign_pos_profile_on_insert(self):
        if self.is_new() and self.terminal_id and self.transaction_date:
            self.pos_profile = resolve_pos_profile(self.terminal_id, self.transaction_date)

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


@frappe.whitelist()
def refresh_all_bank_transaction_locations():
    if not frappe.has_permission("Bank POS Transaction", ptype="write"):
        frappe.throw(_("You do not have permission to update Bank POS Transaction."), frappe.PermissionError)

    terminals = frappe.get_all(
        "Terminal Reference",
        fields=["name", "terminal_id"],
        limit_page_length=0,
    )
    terminal_by_name = {row.name: row.terminal_id for row in terminals if row.terminal_id}
    periods_by_terminal = {row.terminal_id: [] for row in terminals if row.terminal_id}

    if terminal_by_name:
        for row in frappe.get_all(
            "Terminal Location History",
            filters={"parent": ["in", list(terminal_by_name)]},
            fields=["parent", "pos_profile", "from_date", "to_date"],
            order_by="parent asc, from_date asc, idx asc",
            limit_page_length=0,
        ):
            terminal_id = terminal_by_name.get(row.parent)
            if terminal_id:
                periods_by_terminal.setdefault(terminal_id, []).append(row)

    transactions = frappe.get_all(
        "Bank POS Transaction",
        fields=["name", "terminal_id", "transaction_date", "pos_profile"],
        order_by="transaction_date asc, name asc",
        limit_page_length=0,
    )

    from marina_custom_apps.pos_reconciliation.location_service import select_pos_profile

    updated = 0
    resolved = 0
    unresolved = 0

    for row in transactions:
        pos_profile = select_pos_profile(
            periods_by_terminal.get(row.terminal_id, []),
            row.transaction_date,
        )
        if pos_profile:
            resolved += 1
        else:
            unresolved += 1

        old_value = row.pos_profile or None
        new_value = pos_profile or None
        if old_value != new_value:
            frappe.db.set_value(
                "Bank POS Transaction",
                row.name,
                "pos_profile",
                new_value,
                update_modified=False,
            )
            updated += 1

    return {
        "total": len(transactions),
        "resolved": resolved,
        "unresolved": unresolved,
        "updated": updated,
    }
