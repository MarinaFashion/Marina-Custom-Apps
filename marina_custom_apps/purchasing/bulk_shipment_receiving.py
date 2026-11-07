"""Marina Bulk Shipment Receiving.

Excel quantities are in Stock UOM. Preview never writes data; draft construction
uses ERPNext's standard Purchase Order -> Purchase Receipt mapper.
"""
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import flt

MAX_LINES = 1500
MAX_PURCHASE_ORDERS = 500
EPS = 0.000001


def _parse(text):
    text = (text or "").strip()
    if not text:
        frappe.throw(_("Paste Item Code and Received Qty rows first."))
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        frappe.throw(_("Maximum {0} pasted rows.").format(MAX_LINES))
    result, errors = {}, []
    for index, raw in enumerate(lines, 1):
        columns = raw.split("\t") if "\t" in raw else raw.split(",")
        columns = [column.strip() for column in columns]
        if len(columns) != 2:
            errors.append({"row": index, "message": "Expected two columns: Item Code and Qty"})
            continue
        code, amount = columns
        if index == 1 and code.lower() in ("item code", "item_code", "variant", "variant code") and amount.lower() in ("qty", "quantity", "received qty", "received quantity"):
            continue
        if not code or len(code) > 140:
            errors.append({"row": index, "message": "Missing or invalid Item Code"})
            continue
        try:
            qty = Decimal(amount)
            if not qty.is_finite() or qty < 0:
                raise InvalidOperation()
        except (InvalidOperation, ValueError):
            errors.append({"row": index, "item_code": code, "message": "Quantity must be non-negative"})
            continue
        if qty:
            result[code] = result.get(code, Decimal(0)) + qty
    return result, errors


def _lookup(supplier, company, codes):
    if not supplier or not company:
        frappe.throw(_("Select Supplier and Company first."))
    if not frappe.has_permission("Purchase Receipt", "create"):
        frappe.throw(_("Permission denied for Purchase Receipt."), frappe.PermissionError)
    if not codes:
        return {}, {}

    # Match each variant to the PO whose TITLE equals its Item Template.
    # No fuzzy or prefix matching: ambiguity must never silently select a PO.
    items = frappe.get_all(
        "Item",
        filters={"name": ["in", list(codes)]},
        fields=["name", "variant_of"],
        limit_page_length=MAX_LINES,
    )
    templates = {item.name: item.variant_of for item in items}
    titles = sorted({title for title in templates.values() if title})
    if not titles:
        return {}, templates

    parents = frappe.get_list(
        "Purchase Order",
        filters={"docstatus": 1, "supplier": supplier, "company": company,
                 "title": ["in", titles],
                 "status": ["not in", ["Closed", "Cancelled", "Completed"]]},
        fields=["name", "title"],
        limit_page_length=MAX_PURCHASE_ORDERS + 1,
    )
    if len(parents) > MAX_PURCHASE_ORDERS:
        frappe.throw(_("Too many matching Purchase Orders. Narrow the input."))
    if not parents:
        return {}, templates
    parent_titles = {po.name: po.title for po in parents}
    po_items = frappe.get_all(
        "Purchase Order Item",
        filters={"parent": ["in", list(parent_titles)],
                 "item_code": ["in", list(codes)]},
        fields=["name", "parent", "item_code", "qty", "received_qty",
                "conversion_factor", "uom", "stock_uom", "warehouse"],
        limit_page_length=MAX_LINES * 5,
    )
    matches = {}
    for item in po_items:
        template = templates.get(item.item_code)
        if not template or parent_titles.get(item.parent) != template:
            continue
        factor = flt(item.conversion_factor)
        if factor <= 0:
            continue
        outstanding = (flt(item.qty) - flt(item.received_qty)) * factor
        if outstanding <= EPS:
            continue
        matches.setdefault(item.item_code, []).append({
            "po": item.parent, "po_title": template, "po_item": item.name,
            "po_qty": flt(item.qty) * factor,
            "already_received_qty": flt(item.received_qty) * factor,
            "outstanding_qty": outstanding,
            "conversion_factor": factor, "uom": item.uom,
            "stock_uom": item.stock_uom, "warehouse": item.warehouse,
        })
    return matches, templates


def _evaluate(text, supplier, company):
    quantities, errors = _parse(text)
    matches, templates = _lookup(supplier, company, quantities.keys())
    result = []
    for code, quantity in quantities.items():
        candidates = matches.get(code, [])
        qty = float(quantity)
        template = templates.get(code)
        row = {
            "item_code": code, "template": template, "receipt_qty": qty,
            "qty": qty, "candidates": candidates,
        }
        if not template:
            row.update({"status": "Not Found", "message": "Item has no Item Template (variant_of)"})
        elif not candidates:
            row.update({"status": "Not Found", "message": "No outstanding PO item matching template/title"})
        elif len(candidates) > 1:
            row.update({"status": "Ambiguous", "message": "Multiple open PO lines match this variant/template"})
        else:
            selected = candidates[0]
            row["po_title"] = selected["po_title"]
            row["po_qty"] = selected["po_qty"]
            row["outstanding_qty"] = selected["outstanding_qty"]
            row["variance"] = round(qty - selected["outstanding_qty"], 6)
            row["status"] = "Variance" if abs(row["variance"]) > EPS else "Matched"
        result.append(row)
    return result, errors


@frappe.whitelist()
def preview(text, supplier, company):
    rows, errors = _evaluate(text, supplier, company)
    return {"rows": rows, "errors": errors, "total": len(rows),
            "matched": sum(row["status"] in ("Matched", "Variance") for row in rows)}


def _decisions(value):
    decisions = frappe.parse_json(value) if isinstance(value, str) else value
    if not isinstance(decisions, list) or len(decisions) > MAX_LINES:
        frappe.throw(_("Reviewed row decisions are required."))
    output = {}
    for row in decisions:
        if not isinstance(row, dict):
            frappe.throw(_("Invalid review decision."))
        code, action = row.get("item_code"), row.get("decision")
        if not isinstance(code, str) or code in output or action not in ("Accept", "Reject"):
            frappe.throw(_("Duplicate or invalid review decision."))
        output[code] = row
    return output


@frappe.whitelist()
def build_draft(text, supplier, company, decisions):
    """Re-evaluate authoritative data, apply approvals, return an unsaved receipt."""
    rows, errors = _evaluate(text, supplier, company)
    if errors or not rows:
        frappe.throw(_("Resolve invalid input rows before loading."))
    review = _decisions(decisions)
    if set(review) != {r["item_code"] for r in rows}:
        frappe.throw(_("Review decisions do not cover the current pasted items. Preview again."))

    chosen = []
    for row in rows:
        action = review[row["item_code"]]["decision"]
        if action == "Reject":
            continue
        if row["status"] not in ("Matched", "Variance"):
            frappe.throw(_("Item {0} cannot be accepted: {1}").format(row["item_code"], row["status"]))
        candidate = row["candidates"][0]
        # Prevent decisions from being reused if source PO candidates change.
        if review[row["item_code"]].get("po_item") != candidate["po_item"]:
            frappe.throw(_("PO match changed for {0}. Preview again.").format(row["item_code"]))
        chosen.append(row)

    if not chosen:
        frappe.throw(_("Select at least one item for inclusion."))
    from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

    desired = {r["candidates"][0]["po_item"]: r for r in chosen}
    po_names = sorted({r["candidates"][0]["po"] for r in chosen})
    parents = frappe.get_list(
        "Purchase Order",
        filters={"name": ["in", po_names], "docstatus": 1,
                 "supplier": supplier, "company": company},
        fields=["name", "currency"], limit_page_length=len(po_names),
    )
    if len(parents) != len(po_names):
        frappe.throw(_("A Purchase Order is no longer available. Preview again."))
    if len({po.currency for po in parents}) != 1:
        frappe.throw(_("Mixed PO currencies are not supported in one Purchase Receipt."))

    target = None
    for po in po_names:
        selected = [ref for ref, row in desired.items() if row["candidates"][0]["po"] == po]
        target = make_purchase_receipt(po, target_doc=target, args={"filtered_children": selected})
    if not target:
        frappe.throw(_("No eligible Purchase Order lines found."))

    mapped, seen = [], set()
    for item in target.items:
        ref = item.get("purchase_order_item")
        if ref not in desired:
            continue
        if ref in seen:
            frappe.throw(_("Duplicate mapped PO line: {0}").format(ref))
        seen.add(ref)
        row = desired[ref]
        factor = flt(item.conversion_factor)
        if factor <= 0:
            frappe.throw(_("Invalid conversion factor for {0}.").format(item.item_code))
        item.qty = row["receipt_qty"] / factor
        item.received_qty = item.qty
        item.stock_qty = row["receipt_qty"]
        item.amount = flt(item.qty) * flt(item.rate)
        item.base_amount = flt(item.amount) * flt(target.conversion_rate)
        mapped.append(item)
    if set(desired) != seen:
        frappe.throw(_("ERPNext could not map every accepted PO line. No document saved."))
    target.set("items", mapped)
    target.company = company
    target.supplier = supplier
    return target.as_dict()
