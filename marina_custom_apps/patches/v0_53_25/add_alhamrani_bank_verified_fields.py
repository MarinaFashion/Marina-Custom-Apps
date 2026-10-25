"""Add bank-verified fields to the external Alhamrani Transaction on Demo.

The ERPGulf-owned DocType and original terminal evidence are left untouched.
Fields are read-only in the form and writable solely by the audited manual
bank-link enrichment service. This patch performs no historical backfill.
"""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    # The manual-link enrichment feature is still in the Demo acceptance phase.
    # Do not create fields in Live until a separately approved production rollout.
    if getattr(frappe.local, "site", None) != "marinademo.frappe.cloud":
        return
    doctype = "Alhamrani Transaction"
    if not frappe.db.exists("DocType", doctype):
        # ERPGulf integration may be absent on non-POS test environments.
        return
    meta = frappe.get_meta(doctype)
    if not meta.has_field("response_meaning"):
        frappe.throw(
            "Cannot install Bank Verified fields: Alhamrani Transaction "
            "has no Response Meaning field to distinguish manual slips."
        )
    create_custom_fields(
        {
            doctype: [
                {
                    "fieldname": "custom_bank_verified_section",
                    "fieldtype": "Section Break",
                    "label": "Bank Verified Details",
                    "insert_after": "response_meaning",
                    "collapsible": 1,
                    "description": "Information from an explicitly approved Bank POS manual link, not a terminal response.",
                },
                {
                    "fieldname": "custom_bank_masked_pan",
                    "fieldtype": "Data",
                    "label": "Bank Verified Masked Card Number",
                    "insert_after": "custom_bank_verified_section",
                    "read_only": 1,
                    "no_copy": 1,
                    "description": "Masked bank card reference only; never an unmasked card number.",
                },
                {
                    "fieldname": "custom_bank_transaction_time",
                    "fieldtype": "Time",
                    "label": "Bank Verified Transaction Time",
                    "insert_after": "custom_bank_masked_pan",
                    "read_only": 1,
                    "no_copy": 1,
                    "description": "Bank-reported transaction time, not the POS terminal response timestamp.",
                },
            ]
        },
        update=True,
    )
    frappe.clear_cache(doctype=doctype)
