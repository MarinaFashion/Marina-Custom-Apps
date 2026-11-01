"""Explicit, audit-scoped repair for Release 7 variant Item Names.

No migration hook, scheduled job, or automatic repair. Preview and explicit
POST confirmation are required; only the Item Name is changed.
"""
import hashlib
import hmac
import json
import time

import frappe

MAX_REPAIR_VARIANTS = 40
TOKEN_LIFETIME_SECONDS = 300


def _authorized(design_code):
    user = frappe.session.user
    permitted_roles = {"System Manager", "Marina Design Management"}
    if user != "Administrator" and not permitted_roles.intersection(frappe.get_roles(user)):
        frappe.throw("Only designated managers may repair generated Item Names", frappe.PermissionError)
    if not frappe.has_permission("Item", "write", user=user):
        frappe.throw("ERPNext Item write permission required", frappe.PermissionError)
    design = frappe.get_doc("Design Code", design_code)
    if not frappe.has_permission("Design Code", "read", doc=design, user=user):
        frappe.throw("Design Code read permission required", frappe.PermissionError)
    return design


def _audit(design_code, production_key):
    if not production_key:
        frappe.throw("Production Item reference required")
    audit = frappe.get_doc("Design Item Creation", production_key)
    if audit.design_code != design_code:
        frappe.throw("Creation audit does not belong to this Design Code")
    try:
        records = json.loads(audit.variant_snapshot or "[]")
    except (TypeError, ValueError):
        frappe.throw("Invalid creation audit snapshot. Do not repair automatically.")
    if not isinstance(records, list) or not (1 <= len(records) <= MAX_REPAIR_VARIANTS):
        frappe.throw("Invalid or oversized creation audit snapshot")
    return audit, records


def _inspect(audit, records):
    """Return only verifiably generated variants; conservatively skip anything else."""
    template = frappe.db.get_value("Item", audit.template_item, ["name", "item_name", "has_variants"], as_dict=True)
    if not template or not template.has_variants:
        frappe.throw("Recorded Item Template is missing or no longer a Template")

    results = []
    seen = set()
    for entry in records:
        code = entry.get("item_code") if isinstance(entry, dict) else None
        barcode = entry.get("barcode") if isinstance(entry, dict) else None
        if not isinstance(code, str) or code in seen or not code.startswith(audit.template_item + "-"):
            frappe.throw("Creation audit contains an invalid or repeated Variant Item Code")
        if barcode != code:
            frappe.throw("Creation audit contains an unexpected barcode; cannot repair")
        seen.add(code)
        item = frappe.db.get_value("Item", code,
                                  ["name", "item_code", "item_name", "variant_of", "modified"], as_dict=True)
        status = "skip"
        reason = ""
        if not item:
            reason = "Item no longer exists"
        elif item.item_code != code or item.variant_of != audit.template_item:
            reason = "Item identity does not match creation audit"
        elif item.item_name == code:
            reason = "Item Name already correct"
        elif item.item_name != template.item_name:
            reason = "Item Name differs from Template; may be manually edited"
        else:
            # Confirm the code is still represented by the creation-time barcode.
            present = frappe.db.exists("Item Barcode", {
                "parent": code, "parenttype": "Item", "parentfield": "barcodes", "barcode": code
            })
            if present:
                status = "repair"
                reason = "Item Name still equals the Template Item Name"
            else:
                reason = "Expected barcode is missing"
        results.append({"item_code": code, "current_item_name": item.item_name if item else None,
                        "proposed_item_name": code, "status": status, "reason": reason,
                        "modified": str(item.modified) if item else None})
    return results


def _signature(design_code, production_key, entries, issued):
    secret = frappe.conf.get("encryption_key")
    if not secret:
        frappe.throw("Site encryption key is required for repair confirmation")
    payload = json.dumps({
        "design_code": design_code, "production_key": production_key,
        "user": frappe.session.user, "issued": issued, "entries": entries,
    }, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


@frappe.whitelist()
def preview_variant_item_name_repair(design_code, production_key):
    _authorized(design_code)
    audit, records = _audit(design_code, production_key)
    entries = _inspect(audit, records)
    issued = int(time.time())
    return {
        "template_item": audit.template_item, "items": entries,
        "eligible_count": sum(row["status"] == "repair" for row in entries),
        "confirmation_token": "{}:{}".format(
            issued, _signature(design_code, production_key, entries, issued)),
    }


@frappe.whitelist(methods=["POST"])
def confirm_variant_item_name_repair(design_code, production_key, confirmation_token):
    _authorized(design_code)
    try:
        issued_text, mac = confirmation_token.split(":", 1)
        issued = int(issued_text)
    except (AttributeError, TypeError, ValueError):
        frappe.throw("Invalid repair confirmation token")
    if not (0 <= time.time() - issued <= TOKEN_LIFETIME_SECONDS):
        frappe.throw("Repair preview expired; preview again")

    audit, records = _audit(design_code, production_key)
    # Serialize competing repair requests by locking the associated Design Code.
    frappe.db.sql("SELECT name FROM `tabDesign Code` WHERE name=%s FOR UPDATE",
                  (design_code,))
    entries = _inspect(audit, records)
    expected = _signature(design_code, production_key, entries, issued)
    if not hmac.compare_digest(expected, mac):
        frappe.throw("Item state changed since preview; preview the repair again")
    eligible = [row for row in entries if row["status"] == "repair"]
    if not eligible:
        return {"repaired": [], "skipped": len(entries)}
    for row in eligible:
        doc = frappe.get_doc("Item", row["item_code"])
        if str(doc.modified) != row["modified"] or doc.item_name != row["current_item_name"] \
                or doc.variant_of != audit.template_item:
            frappe.throw("An Item changed during repair; preview again")
        doc.item_name = row["proposed_item_name"]
        doc.save()
        doc.add_comment("Info", text="Release 7 verified Item Name correction: {} → {}. Initiated by {}.".format(
            row["current_item_name"], row["proposed_item_name"], frappe.session.user))
    return {"repaired": [row["item_code"] for row in eligible],
            "skipped": len(entries) - len(eligible)}
