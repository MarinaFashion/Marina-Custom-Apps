"""One-time ERPNext Item creation audit with conditional, permissioned deletion.

Audit fields remain immutable. System Managers may delete an audit document
only after every recorded ERPNext Item (Template and Variants) is gone.
Deletion never deletes ERPNext Items or changes the original Design Code.
"""
import json

import frappe
from frappe.model.document import Document

MAX_RECORDED_VARIANTS = 40


class DesignItemCreation(Document):
    def validate(self):
        if not self.is_new():
            frappe.throw("Item Creation audit records are immutable")

    def on_trash(self):
        # Native delete permission is required as well. Do not allow elevated
        # ignore_permissions callers to bypass this explicit security policy.
        user = frappe.session.user
        if user != "Administrator" and "System Manager" not in frappe.get_roles(user):
            frappe.throw(
                "Only System Manager or Administrator may delete Item Creation records",
                frappe.PermissionError,
            )

        # Same serialization lock as confirm_item_creation. After deleting an
        # audit, a subsequent create is allowed only through normal preview,
        # confirmation, Item/barcode collision and permission checks.
        locked = frappe.db.sql(
            "SELECT name FROM `tabDesign Code` WHERE name=%s FOR UPDATE",
            (self.design_code,),
        )
        if not locked:
            frappe.throw("Linked Design Code no longer exists; manual review is required")

        template_code = self.template_item
        if not isinstance(template_code, str) or not template_code.strip():
            frappe.throw("Creation audit has no Template Item Code; manual review required")

        try:
            records = json.loads(self.variant_snapshot or "[]")
        except (TypeError, ValueError):
            frappe.throw("Creation audit Variant Snapshot is invalid; manual review required")
        if not isinstance(records, list) or not (1 <= len(records) <= MAX_RECORDED_VARIANTS):
            frappe.throw("Creation audit Variant Snapshot is incomplete; manual review required")

        item_codes = {template_code}
        for row in records:
            if not isinstance(row, dict):
                frappe.throw("Invalid Variant Snapshot row; manual review required")
            code = row.get("item_code")
            if not isinstance(code, str) or not code.startswith(template_code + "-"):
                frappe.throw("Invalid recorded Variant Item Code; manual review required")
            if code in item_codes:
                frappe.throw("Duplicate recorded Item Code; manual review required")
            item_codes.add(code)

        remaining = frappe.get_all(
            "Item",
            filters={"item_code": ["in", sorted(item_codes)]},
            pluck="item_code",
            limit_page_length=len(item_codes),
        )
        # Also guard unexpected variants not in the snapshot (e.g. added later).
        # A linked variant is still an ERPNext Item belonging to this Template.
        extra_variants = frappe.get_all(
            "Item",
            filters={"variant_of": template_code},
            pluck="item_code",
            limit_page_length=10,
        )
        remaining = sorted(set(remaining) | set(extra_variants))
        if remaining:
            frappe.throw(
                "Cannot delete Design Item Creation while generated ERPNext Items still "
                "exist. Delete the Template and all Variants first. Remaining: "
                + ", ".join(remaining[:10])
                + (" (additional Items exist)" if len(remaining) > 10 else "")
            )
