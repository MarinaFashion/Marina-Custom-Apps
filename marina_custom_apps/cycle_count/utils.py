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
    rows = frappe.get_all("Bin",
        filters={"warehouse": warehouse, "item_code": ["in", item_codes]},
        fields=["item_code","actual_qty","valuation_rate"], limit_page_length=0)
    return {r.item_code: {"qty": flt(r.actual_qty), "rate": flt(r.valuation_rate)} for r in rows}

def primary_barcodes(item_codes):
    rows = frappe.get_all("Item Barcode", filters={"parent": ["in", item_codes]},
        fields=["parent","barcode","idx"], order_by="parent asc, idx asc", limit_page_length=0)
    out={}
    for r in rows:
        if r.parent not in out and r.barcode:
            out[r.parent]=r.barcode
    return out

def sizes(item_codes):
    rows = frappe.get_all("Item Variant Attribute",
        filters={"parent": ["in", item_codes], "attribute": ["in", ["Size","SIZE","size"]]},
        fields=["parent","attribute_value","idx"], order_by="parent asc, idx asc", limit_page_length=0)
    out={}
    for r in rows:
        if r.parent not in out and r.attribute_value:
            out[r.parent]=r.attribute_value
    return out
