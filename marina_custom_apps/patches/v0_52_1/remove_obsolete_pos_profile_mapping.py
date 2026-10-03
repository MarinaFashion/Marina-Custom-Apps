from __future__ import annotations

import frappe


OBSOLETE_DOCTYPE = "POS Reconciliation Profile Mapping"


def execute():
    # v0.52.1 uses the standard POS Profile.cost_center field as the single
    # source of truth for future commission/VAT accounting. Remove the temporary
    # mapping child DocType introduced in v0.52.0 after model sync removes the
    # settings table field.
    if frappe.db.exists("DocType", OBSOLETE_DOCTYPE):
        frappe.delete_doc(
            "DocType",
            OBSOLETE_DOCTYPE,
            force=True,
            ignore_permissions=True,
            ignore_missing=True,
        )

    frappe.clear_cache()
