"""Bulk Shipment Receiving: preview and draft-only mapping for Purchase Receipts.

Pasted quantities are expressed in stock UOM. Never writes inventory or submits documents.
"""
from collections import Counter
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import flt

MAX_LINES = 1500
MAX_PURCHASE_ORDERS = 500


def _parse(text):
    text = (text or "").strip()
    if not text:
        frappe.throw(_("Paste Item Code and Received Qty rows first."))
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        frappe.throw(_("Maximum {0} pasted rows.").format(MAX_LINES))
    data = {}
    errors = []
    for index, raw in enumerate(lines, 1):
        parts = raw.split("\t") if "\t" in raw else raw.split(",")
        parts = [p.strip() for p in parts]
        if len(parts) != 2:
            errors.append({"row": index, "message": "Expected two columns: Item Code and Qty"})
            continue
        code, value = parts
        if index == 1 and code.lower() in ("item code", "item_code", "variant", "variant code") and value.lower() in ("qty", "quantity", "received qty", "received quantity"):
            continue
        if not code or len(code) > 140:
            errors.append({"row": index, "message": "Missing or invalid Item Code"})
            continue
        try:
            qty = Decimal(value)
            if not qty.is_finite() or qty < 0:
                raise InvalidOperation()
        except (InvalidOperation, ValueError):
            errors.append({"row": index, "item_code": code, "message": "Quantity must be a non-negative number"})
            continue
        if qty == 0:
            continue
        data[code] = data.get(code, Decimal(0)) + qty
    return data, errors


def _lookup(supplier, company, codes):
    if not supplier or not company:
        frappe.throw(_("Select Supplier and Company on the Purchase Receipt first."))
    if not frappe.has_permission("Purchase Receipt", "create"):
        frappe.throw(_("You do not have permission to create Purchase Receipts."), frappe.PermissionError)
    if not codes:
        return {}
    # Check parent document permissions and supplier/company constraints before
    # accessing PO Item rows, rather than using an unrestricted parent join.
    po_names = frappe.get_list(
        "Purchase Order",
        filters={"docstatus": 1, "supplier": supplier, "company": company,
                 "status": ["not in", ["Closed", "Cancelled", "Completed"]]},
        pluck="name", limit_page_length=MAX_PURCHASE_ORDERS + 1,
    )
    if len(po_names) > MAX_PURCHASE_ORDERS:
        frappe.throw(_("Too many eligible Purchase Orders; narrow the search or contact IT."))
    if not po_names:
        return {}
    rows = frappe.get_all(
        "Purchase Order Item",
        filters={"parent": ["in", po_names], "item_code": ["in", list(codes)]},
        fields=["name", "parent", "item_code", "qty", "stock_qty", "received_qty",
                "conversion_factor", "uom", "stock_uom", "warehouse"],
        limit_page_length=MAX_LINES * 5,
    )
    found = {}
    for row in rows:
        factor = flt(row.conversion_factor)
        if factor <= 0:
            continue
        remaining = (flt(row.qty) - flt(row.received_qty)) * factor
        if remaining > 0.000001:
            found.setdefault(row.item_code, []).append({
                "po": row.parent, "po_item": row.name,
                "remaining_stock_qty": remaining,
                "uom": row.uom, "stock_uom": row.stock_uom,
                "conversion_factor": factor,
                "warehouse": row.warehouse,
            })
    return found


def _evaluate(text, supplier, company):
    data, parse_errors = _parse(text)
    matches = _lookup(supplier, company, data.keys())
    result = []
    for code, quantity in data.items():
        candidates = matches.get(code, [])
        q = float(quantity)
        if not candidates:
            result.append({"item_code": code, "qty": q, "status": "Not Found",
                           "message": "No outstanding submitted PO item for this supplier/company"})
        elif len(candidates) != 1:
            result.append({"item_code": code, "qty": q, "status": "Ambiguous",
                           "message": "Multiple eligible PO Item rows; resolve manually",
                           "candidates": candidates})
        elif q > candidates[0]["remaining_stock_qty"] + 0.000001:
            result.append({"item_code": code, "qty": q, "status": "Exceeds Outstanding",
                           "message": "Received quantity exceeds outstanding Stock UOM quantity",
                           "candidates": candidates})
        else:
            result.append({"item_code": code, "qty": q, "status": "Matched",
                           "candidates": candidates})
    return result, parse_errors


@frappe.whitelist()
def preview(text, supplier, company):
    items, errors = _evaluate(text, supplier, company)
    return {"rows": items, "errors": errors,
            "matched": sum(r["status"] == "Matched" for r in items),
            "total": len(items)}


@frappe.whitelist()
def build_draft(text, supplier, company):
    """Return a mapped, unsaved PR document; never insert or submit anything."""
    rows, errors = _evaluate(text, supplier, company)
    if errors or not rows or any(row["status"] != "Matched" for row in rows):
        frappe.throw(_("Resolve all unmatched, ambiguous, excess-quantity or invalid rows first."))
    from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

    desired = {r["candidates"][0]["po_item"]: r for r in rows}
    po_names = sorted({r["candidates"][0]["po"] for r in rows})
    target = None
    for po in po_names:
        # ERPNext's standard mapper preserves PO Item references, taxes and
        # other purchasing fields. Target remains unsaved throughout.
        target = make_purchase_receipt(po, target_doc=target)
    if not target:
        frappe.throw(_("No eligible Purchase Order items found."))
    target_items = []
    seen = set()
    for item in target.items:
        ref = item.get("purchase_order_item")
        if ref not in desired:
            continue
        if ref in seen:
            frappe.throw(_("Duplicate mapped Purchase Order Item: {0}").format(ref))
        seen.add(ref)
        request = desired[ref]
        factor = flt(item.conversion_factor)
        if factor <= 0:
            frappe.throw(_("Invalid conversion factor on {0}.").format(item.item_code))
        item.qty = request["qty"] / factor
        item.received_qty = request["qty"] / factor\n        item.stock_qty = request["qty"]
        target_items.append(item)
    if set(desired) != seen:
        frappe.throw(_("Standard ERPNext mapper could not map all selected PO lines. No document was saved."))
    target.set("items", target_items)
    target.supplier = supplier
    target.company = company
    return target.as_dict()
