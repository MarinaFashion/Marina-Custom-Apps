import frappe
from frappe.model.document import Document

from marina_custom_apps.pos_reconciliation.location_service import (
    clear_terminal_period_cache,
    select_pos_profile,
    validate_location_periods,
)


def clean_text(value) -> str:
    return str(value or "").strip()


class TerminalReference(Document):
    def validate(self):
        self.terminal_id = clean_text(self.terminal_id)
        self.retailer_identifier = clean_text(self.retailer_identifier)
        validate_location_periods(self.get("locations") or [])

    def on_update(self):
        clear_terminal_period_cache(self.terminal_id)


@frappe.whitelist()
def refresh_bank_transaction_locations(terminal_reference):
    doc = frappe.get_doc("Terminal Reference", terminal_reference)
    doc.check_permission("write")

    periods = doc.get("locations") or []
    validate_location_periods(periods)

    transactions = frappe.get_all(
        "Bank POS Transaction",
        filters={"terminal_id": doc.terminal_id},
        fields=["name", "transaction_date", "pos_profile"],
        order_by="transaction_date asc, name asc",
        limit_page_length=0,
    )

    updated = 0
    resolved = 0
    unresolved = 0

    for row in transactions:
        pos_profile = select_pos_profile(periods, row.transaction_date)
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

    clear_terminal_period_cache(doc.terminal_id)

    return {
        "terminal_id": doc.terminal_id,
        "total": len(transactions),
        "resolved": resolved,
        "unresolved": unresolved,
        "updated": updated,
    }
