"""Create one read-only bank-sourced time field on Demo's Alhamrani Transaction.

Normal terminal time is part of the terminal's original response_json.
The manually confirmed Bank POS time must remain a separately labelled value.
This patch never edits existing Alhamrani payments or response payloads.
"""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    # Limited to Demo pending explicit production acceptance.
    if getattr(frappe.local, "site", "") != "marinademo.frappe.cloud":
        return

    doctype = "Alhamrani Transaction"
    if not frappe.db.exists("DocType", doctype):
        return

    meta = frappe.get_meta(doctype)
    if not meta.has_field("response_meaning") or not meta.has_field("pan"):
        frappe.throw(
            "Alhamrani schema is missing expected manual-slip evidence or Masked PAN. "
            "Bank POS Transaction Time field was not created."
        )

    create_custom_fields(
        {
            doctype: [
                {
                    "fieldname": "custom_bank_verified_transaction_time",
                    "label": "Bank POS Transaction Time",
                    "fieldtype": "Time",
                    "insert_after": "pan",
                    "read_only": 1,
                    "no_copy": 1,
                    "description": (
                        "Bank-reported time from an approved manual POS link; "
                        "not a terminal response time."
                    ),
                }
            ]
        },
        update=True,
    )
    frappe.clear_cache(doctype=doctype)
