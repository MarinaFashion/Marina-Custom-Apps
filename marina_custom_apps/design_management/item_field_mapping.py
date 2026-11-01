"""Validate one-time direct Item field mappings (no Item writes)."""
import re

import frappe

SOURCE_DOCTYPES = {"Design Code", "Design Production Item"}
VALUE_TYPES = {"Data", "Small Text", "Text", "Select", "Link", "Date", "Int",
               "Float", "Currency", "Check", "Attach", "Attach Image"}
SYSTEM_FIELDS = {
    "item_code", "variant_of", "has_variants", "attributes", "stock_uom",
    "item_group", "valuation_rate", "standard_rate", "opening_stock",
    "is_stock_item", "disabled", "name", "naming_series",
}
FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,139}$")

def _blocked_target_field(df):
    """Only Item.image may bypass hidden=True, never other safety rules.

    ERPNext v15's standard Item image DocField is intentionally hidden because
    Item displays the image separately. Its URL is nevertheless writable.
    """
    return bool(
        df.fieldname in SYSTEM_FIELDS
        or df.read_only
        or (df.hidden and not (
            df.fieldname == "image" and df.fieldtype == "Attach Image"
        ))
        or df.set_only_once
        or df.unique
    )



def validate_item_field_mappings(rows):
    """Fail closed: only safe scalar DocFields; no computed expressions or core variant fields.

    Both/Template/Variant target overlap is disallowed, preventing ambiguous precedence.
    This validates configuration only. Actual Item creation will revalidate at preview
    and confirmation against site-specific Item metadata and required fields.
    """
    seen = set()
    if len(rows or []) > 100:
        frappe.throw("A maximum of 100 Item Field Mapping rows is supported")
    for row in rows or []:
        if not row.is_active:
            continue
        source_doctype = row.source_doctype
        source_field = (row.source_field or "").strip()
        target_field = (row.target_field or "").strip()
        apply_to = row.apply_to
        if source_doctype not in SOURCE_DOCTYPES or apply_to not in {"Template", "Variant", "Both"}:
            frappe.throw("Invalid Item Mapping source or application scope")
        if not FIELD_RE.fullmatch(source_field) or not FIELD_RE.fullmatch(target_field):
            frappe.throw("Item Mapping field names must be valid technical fieldnames")
        if target_field in SYSTEM_FIELDS:
            frappe.throw("Item Mapping cannot override system-managed Item field: " + target_field)
        source_meta = frappe.get_meta(source_doctype)
        target_meta = frappe.get_meta("Item")
        src = source_meta.get_field(source_field)
        dst = target_meta.get_field(target_field)
        if not src or not dst or src.fieldtype not in VALUE_TYPES or dst.fieldtype not in VALUE_TYPES:
            frappe.throw("Item Mapping requires supported scalar source and target fields")
        if _blocked_target_field(dst):
            frappe.throw("Item Mapping target cannot be read-only, hidden, unique or set-once")
        if dst.fieldtype == "Link" and (src.fieldtype != "Link" or src.options != dst.options):
            frappe.throw("Link Item Mapping requires matching linked DocTypes")
        if dst.fieldtype in {"Date", "Check", "Int", "Float", "Currency"} and src.fieldtype != dst.fieldtype:
            frappe.throw("Item Mapping numeric/date/check field types must match exactly")
        if src.fieldtype in {"Attach", "Attach Image"} and dst.fieldtype not in {"Attach", "Attach Image", "Data"}:
            frappe.throw("Attachment Item Mapping target must support image/file URLs")
        scopes = ("Template", "Variant") if apply_to == "Both" else (apply_to,)
        for scope in scopes:
            key = (scope, target_field)
            if key in seen:
                frappe.throw("Duplicate Item Mapping target for " + scope + ": " + target_field)
            seen.add(key)
        row.source_field = source_field
        row.target_field = target_field


def _available_fields(doctype, *, target=False):
    """Use site metadata, including Item Custom Fields; exclude unsupported fields."""
    result = []
    for df in frappe.get_meta(doctype).fields:
        if df.fieldtype not in VALUE_TYPES or not FIELD_RE.fullmatch(df.fieldname or ""):
            continue
        if target and _blocked_target_field(df):
            continue
        result.append({"fieldname": df.fieldname, "label": df.label or df.fieldname,
                       "fieldtype": df.fieldtype, "options": df.options or ""})
    return result


@frappe.whitelist()
def get_item_mapping_field_options():
    """Return curated field choices only to users allowed to change Design Settings."""
    if not frappe.has_permission("Design Management Settings", "write"):
        frappe.throw("Not permitted to configure Item mappings", frappe.PermissionError)
    return {
        "sources": {doctype: _available_fields(doctype)
                    for doctype in sorted(SOURCE_DOCTYPES)},
        "targets": _available_fields("Item", target=True),
    }
