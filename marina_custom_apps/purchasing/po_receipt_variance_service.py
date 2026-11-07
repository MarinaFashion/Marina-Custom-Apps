"""PO vs Purchase Receipt Variance & Discount — management-only report.

Totals are aggregated by variant across *all* submitted purchase orders and
submitted, PO-linked purchase receipts for the chosen supplier/company.
No accounting documents or stock transactions are created.
"""
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

BATCH_SIZE = 250
EPS = 0.000001


def _chunks(values, size=BATCH_SIZE):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def calculate(ordered, received, cost_per_stock_unit, tolerance_pct=5, discount_pct=50):
    """All quantities are in Stock UOM; rates are company base currency per Stock UOM.

    The eligible quantity is ONLY units beyond the tolerance band.
    Shortages incur no discount/charge.
    """
    ordered = flt(ordered)
    received = flt(received)
    rate = flt(cost_per_stock_unit)
    tol = flt(tolerance_pct) / 100
    discount = flt(discount_pct) / 100
    variance = received - ordered
    tolerance_qty = ordered * tol
    eligible = max(received - ordered - tolerance_qty, 0)
    return {
        "variance_qty": variance,
        "variance_pct": (variance / ordered * 100) if ordered else 0,
        "tolerance_qty": tolerance_qty,
        "eligible_excess_qty": eligible,
        "discount_value": eligible * rate * discount,
        "shortage_qty": max(ordered - received, 0),
    }


def get_columns():
    def col(label, field, fieldtype="Float", width=120, options=None):
        result = {"label": _(label), "fieldname": field,
                  "fieldtype": fieldtype, "width": width}
        if options:
            result["options"] = options
        if fieldtype == "Float":
            result["precision"] = 3
        return result

    return [
        col("Item Variant", "item_code", "Link", 200, "Item"),
        col("Item Template", "item_template", "Link", 180, "Item"),
        col("Year", "item_year", "Data", 85),
        col("Season", "season", "Data", 110),
        col("Collection", "collection", "Data", 130),
        col("PO Qty", "po_qty"),
        col("Receipt Qty", "receipt_qty"),
        col("Variance Qty", "variance_qty"),
        col("Variance %", "variance_pct", "Percent", 105),
        col("Shortage Qty", "shortage_qty"),
        col("Tolerance Qty", "tolerance_qty"),
        col("Eligible Excess Qty", "eligible_excess_qty", "Float", 145),
        col("Avg PO Cost / Stock Unit", "unit_cost", "Currency", 165, "currency"),
        col("Eligible Discount Value", "discount_value", "Currency", 170, "currency"),
        col("Currency", "currency", "Link", 95, "Currency"),
        col("PO Lines", "po_lines", "Int", 90),
        col("Receipt Lines", "receipt_lines", "Int", 105),
    ]


def _validate(filters):
    if not filters.get("company") or not filters.get("supplier"):
        frappe.throw(_("Company and Supplier are required."))
    if not frappe.has_permission("Purchase Order", "read") or not frappe.has_permission("Purchase Receipt", "read"):
        frappe.throw(_("Read access to both Purchase Orders and Purchase Receipts is required."), frappe.PermissionError)
    for field in ("tolerance_pct", "discount_pct"):
        number = flt(filters.get(field, 5 if field == "tolerance_pct" else 50))
        if number < 0 or number > 100:
            frappe.throw(_("{0} must be between 0 and 100.").format(field))
        filters[field] = number
    if not frappe.db.exists("Company", filters["company"]):
        frappe.throw(_("Invalid company."))
    return frappe.get_cached_value("Company", filters["company"], "default_currency")


def _purchase_order_rows(filters):
    # Parent query is permission-aware. Children are then scoped to these parents.
    names = frappe.get_list(
        "Purchase Order",
        filters={"docstatus": 1, "company": filters["company"],
                 "supplier": filters["supplier"]},
        pluck="name", limit_page_length=0,
    )
    for group in _chunks(names):
        yield from frappe.get_all(
            "Purchase Order Item",
            filters={"parent": ["in", group]},
            fields=["name", "parent", "item_code", "qty",
                    "conversion_factor", "base_rate"],
            limit_page_length=0,
        )


def _receipt_rows(filters, codes):
    """All submitted receipts for this supplier/company, with or without PO links.

    Return documents reverse accepted quantities. Rejected quantities are not
    treated as purchased/accepted stock.
    """
    parents = frappe.get_list(
        "Purchase Receipt",
        filters={"docstatus": 1, "company": filters["company"],
                 "supplier": filters["supplier"]},
        fields=["name", "is_return"],
        limit_page_length=0,
    )
    signs = {row.name: (-1 if row.is_return else 1) for row in parents}
    code_set = set(codes)
    for group in _chunks(list(signs)):
        for row in frappe.get_all(
            "Purchase Receipt Item",
            filters={"parent": ["in", group]},
            fields=["parent", "item_code", "qty", "conversion_factor"],
            limit_page_length=0,
        ):
            if row.item_code not in code_set:
                continue
            quantity = flt(row.qty) * flt(row.conversion_factor)
            # ERPNext normally stores negative qty on a return; also handle
            # legacy positive qty return rows defensively.
            if signs[row.parent] < 0:
                quantity = -abs(quantity)
            yield row.item_code, quantity

def _classifications(codes):
    fields = ["name", "variant_of"]
    meta = frappe.get_meta("Item")
    available = [f for f in ("item_year", "season", "collection") if meta.has_field(f)]
    fields += available
    variants = {}
    for group in _chunks(sorted(codes)):
        for item in frappe.get_all(
            "Item", filters={"name": ["in", group]},
            fields=fields, limit_page_length=0,
        ):
            variants[item.name] = item
    templates = {}
    template_names = {v.variant_of for v in variants.values() if v.variant_of}
    for group in _chunks(sorted(template_names)):
        for item in frappe.get_all(
            "Item", filters={"name": ["in", group]},
            fields=fields, limit_page_length=0,
        ):
            templates[item.name] = item
    return variants, templates


def get_data(filters, currency):
    groups = defaultdict(lambda: {"po_qty": 0.0, "po_amount": 0.0,
                                  "receipt_qty": 0.0, "po_lines": 0,
                                  "receipt_lines": 0})
    for item in _purchase_order_rows(filters):
        factor = flt(item.conversion_factor)
        if not item.item_code or factor <= 0:
            continue
        quantity = flt(item.qty) * factor
        rec = groups[item.item_code]
        rec["po_qty"] += quantity
        rec["po_amount"] += flt(item.qty) * flt(item.base_rate)
        rec["po_lines"] += 1

    if not groups:
        return []

    # Include every submitted Purchase Receipt for the same supplier/company,
    # even if it originated outside the PO mapper. Aggregate all received
    # quantities by variant; returns reduce net accepted receipts.
    for code, qty in _receipt_rows(filters, groups):
        groups[code]["receipt_qty"] += qty
        groups[code]["receipt_lines"] += 1

    variants, templates = _classifications(groups)
    results = []
    for code, amounts in groups.items():
        variant = variants.get(code)
        template_name = variant.variant_of if variant and variant.variant_of else code
        template = templates.get(template_name)
        def field(name):
            return (template.get(name) if template and template.get(name) else
                    variant.get(name) if variant else None)
        year = field("item_year")
        season = field("season")
        collection = field("collection")
        if filters.get("item_year") and str(year or "") != str(filters["item_year"]):
            continue
        if filters.get("season") and season != filters["season"]:
            continue
        if filters.get("collection") and collection != filters["collection"]:
            continue
        ordered = amounts["po_qty"]
        received = amounts["receipt_qty"]
        rate = (amounts["po_amount"] / ordered) if abs(ordered) > EPS else 0
        row = {
            "item_code": code, "item_template": template_name,
            "item_year": year, "season": season, "collection": collection,
            "po_qty": ordered, "receipt_qty": received, "unit_cost": rate,
            "currency": currency, "po_lines": amounts["po_lines"],
            "receipt_lines": amounts["receipt_lines"],
        }
        row.update(calculate(ordered, received, rate,
                             filters["tolerance_pct"], filters["discount_pct"]))
        results.append(row)
    return sorted(results, key=lambda r: (r["item_template"] or "", r["item_code"]))


def execute(filters=None):
    filters = frappe._dict(filters or {})
    currency = _validate(filters)
    return get_columns(), get_data(filters, currency)
