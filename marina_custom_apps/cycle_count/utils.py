import frappe
from frappe import _
from frappe.utils import flt


def is_stock_manager(user=None):
    user = user or frappe.session.user
    return user == "Administrator" or "Stock Manager" in frappe.get_roles(user)


def require_stock_manager():
    if not is_stock_manager():
        frappe.throw(_("Only Stock Manager can perform this action."), frappe.PermissionError)


def ensure_counter(doc):
    if is_stock_manager():
        return
    if doc.assigned_to != frappe.session.user:
        frappe.throw(_("This count is assigned to another user."), frappe.PermissionError)


def bin_snapshot(warehouse, item_codes):
    rows = frappe.get_all(
        "Bin",
        filters={"warehouse": warehouse, "item_code": ["in", item_codes]},
        fields=["item_code", "actual_qty", "valuation_rate"],
        limit_page_length=0,
    )
    return {
        r.item_code: {"qty": flt(r.actual_qty), "rate": flt(r.valuation_rate)}
        for r in rows
    }


def primary_barcodes(item_codes):
    rows = frappe.get_all(
        "Item Barcode",
        filters={"parent": ["in", item_codes]},
        fields=["parent", "barcode", "idx"],
        order_by="parent asc, idx asc",
        limit_page_length=0,
    )
    out = {}
    for r in rows:
        if r.parent not in out and r.barcode:
            out[r.parent] = r.barcode
    return out


def _size_abbreviations(values):
    values = list({v for v in values if v})
    if not values:
        return {}

    rows = frappe.get_all(
        "Item Attribute Value",
        filters={
            "parent": "Size",
            "parenttype": "Item Attribute",
            "attribute_value": ["in", values],
        },
        fields=["attribute_value", "abbr"],
        limit_page_length=0,
    )
    return {
        r.attribute_value: (r.abbr or r.attribute_value)
        for r in rows
        if r.attribute_value
    }


def size_abbreviation(value):
    if not value:
        return value
    return _size_abbreviations([value]).get(value, value)


def sizes(item_codes):
    rows = frappe.get_all(
        "Item Variant Attribute",
        filters={
            "parent": ["in", item_codes],
            "attribute": ["in", ["Size", "SIZE", "size"]],
        },
        fields=["parent", "attribute_value", "idx"],
        order_by="parent asc, idx asc",
        limit_page_length=0,
    )

    raw = {}
    for r in rows:
        if r.parent not in raw and r.attribute_value:
            raw[r.parent] = r.attribute_value

    abbreviations = _size_abbreviations(raw.values())
    return {
        item_code: abbreviations.get(value, value)
        for item_code, value in raw.items()
    }
