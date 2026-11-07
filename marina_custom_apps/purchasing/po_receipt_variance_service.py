"""PO vs Purchase Receipt Variance & Discount — management-only report.

Totals include all submitted purchase orders and submitted purchase receipts
for the selected supplier/company, regardless of original PO/receipt mapping.
Template rollups sum independently calculated variant-level allowances and discounts.
No accounting documents or stock transactions are created.
"""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

import frappe
from frappe import _
from frappe.utils import flt

BATCH_SIZE = 250
EPS = 0.000001
# Contractual over-receipt allowance applies to EACH Item Variant, never to the template.
DEFAULT_TOLERANCE_PCT = 8


def _chunks(values, size=BATCH_SIZE):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def calculate(ordered, received, cost_per_stock_unit, discount_pct=50, tolerance_pct=DEFAULT_TOLERANCE_PCT):
    """All quantities are in Stock UOM; rate is selected currency per Stock UOM.

    The eligible quantity is ONLY units beyond the tolerance band.
    Shortages incur no discount/charge.
    """
    ordered = flt(ordered)
    received = flt(received)
    rate = flt(cost_per_stock_unit)
    tol = flt(tolerance_pct) / 100
    discount = flt(discount_pct) / 100
    variance = received - ordered
    # Match Excel ROUND(x, 0), rather than Python bankers rounding.
    tolerance_qty = float((Decimal(str(max(ordered, 0))) * Decimal(str(tol))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    ))
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
        col("Variants", "variant_count", "Int", 85),
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
    for name, default in (("tolerance_pct", DEFAULT_TOLERANCE_PCT),
                          ("discount_pct", 50)):
        # Explicit zero is valid; only missing or blank values use the default.
        raw = filters.get(name)
        value = flt(default if raw is None or raw == "" else raw)
        if value < 0 or value > 100:
            frappe.throw(_("{0} must be between 0 and 100.").format(name))
        filters[name] = value
    if not frappe.db.exists("Company", filters["company"]):
        frappe.throw(_("Invalid company."))
    base_currency = frappe.get_cached_value("Company", filters["company"], "default_currency")
    selected = filters.get("report_currency") or "CNY"
    if selected not in ("CNY", "SAR"):
        frappe.throw(_("Report Currency must be CNY or SAR."))
    if selected == "SAR" and base_currency != "SAR":
        frappe.throw(_("SAR mode requires the company's base currency to be SAR."))
    filters["report_currency"] = selected
    return selected


def _purchase_order_rows(filters):
    # Parent query is permission-aware. Children are then scoped to these parents.
    parents = frappe.get_list(
        "Purchase Order",
        filters={"docstatus": 1, "company": filters["company"],
                 "supplier": filters["supplier"]},
        fields=["name", "currency"], limit_page_length=0,
    )
    currencies = {p.name: p.currency for p in parents}
    for group in _chunks(list(currencies)):
        for item in frappe.get_all(
            "Purchase Order Item",
            filters={"parent": ["in", group]},
            fields=["name", "parent", "item_code", "qty",
                    "conversion_factor", "rate", "base_rate"],
            limit_page_length=0,
        ):
            item["document_currency"] = currencies[item.parent]
            yield item


def _receipt_rows(filters, codes):
    """All submitted receipts for this supplier/company, with or without PO links.

    Return documents reverse accepted quantities. Rejected quantities are not
    treated as purchased/accepted stock.
    """
    parents = frappe.get_list(
        "Purchase Receipt",
        filters={"docstatus": 1, "company": filters["company"],
                 "supplier": filters["supplier"]},
        fields=["name", "is_return", "currency"],
        limit_page_length=0,
    )
    signs = {row.name: (-1 if row.is_return else 1) for row in parents}
    receipt_currencies = {row.name: row.currency for row in parents}
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
            yield row.item_code, quantity, receipt_currencies[row.parent]

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
        if currency == "CNY" and item.document_currency != "CNY":
            frappe.throw(_("Purchase Order {0} for item {1} is in {2}, not CNY. "
                           "Cannot mix currencies in a supplier report.").format(
                               item.parent, item.item_code, item.document_currency))
        quantity = flt(item.qty) * factor
        rec = groups[item.item_code]
        rec["po_qty"] += quantity
        # PO rate is in the document currency; base_rate is in company currency.
        # Both are weighted from each original PO line, never a current FX quote.
        line_rate = item.rate if currency == "CNY" else item.base_rate
        rec["po_amount"] += flt(item.qty) * flt(line_rate)
        rec["po_lines"] += 1

    if not groups:
        return []

    # Include every submitted Purchase Receipt for the same supplier/company,
    # even if it originated outside the PO mapper. Aggregate all received
    # quantities by variant; returns reduce net accepted receipts.
    for code, qty, receipt_currency in _receipt_rows(filters, groups):
        if receipt_currency != "CNY":
            frappe.throw(_("Purchase Receipt for item {0} is in {1}, not CNY. "
                           "Review transaction currency before sharing the report.").format(
                               code, receipt_currency))
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
            "variant_count": 1,
            "currency": currency, "po_lines": amounts["po_lines"],
            "receipt_lines": amounts["receipt_lines"],
        }
        # Calculate tolerance and discount BEFORE rolling up to Item Template.
        row.update(calculate(ordered, received, rate, filters["discount_pct"],
                             filters["tolerance_pct"]))
        results.append(row)
    if filters.get("view_level", "Item Variant") == "Item Template":
        results = _collapse_templates(results)
    return sorted(results, key=lambda r: (r["item_template"] or "", r["item_code"] or ""))


def _collapse_templates(rows):
    """Display-only rollup of variant-specific allowances and discounts.

    Quantities are summed for display, but variant excess is never offset by
    shortages of another size or colour. Variant-specific PO rates are
    preserved in the estimated supplier discount value.
    """
    grouped = {}
    for row in rows:
        key = row["item_template"]
        group = grouped.setdefault(key, {
            "item_code": None, "item_template": key,
            "item_year": row["item_year"], "season": row["season"],
            "collection": row["collection"], "currency": row["currency"],
            "po_qty": 0.0, "receipt_qty": 0.0, "po_amount": 0.0,
            "variance_qty": 0.0, "shortage_qty": 0.0,
            "tolerance_qty": 0.0, "eligible_excess_qty": 0.0,
            "discount_value": 0.0,
            "variant_count": 0, "po_lines": 0, "receipt_lines": 0,
        })
        group["po_qty"] += row["po_qty"]
        group["receipt_qty"] += row["receipt_qty"]
        group["po_amount"] += row["unit_cost"] * row["po_qty"]
        for field in ("variance_qty", "shortage_qty", "tolerance_qty",
                      "eligible_excess_qty", "discount_value",
                      "variant_count", "po_lines", "receipt_lines"):
            group[field] += row[field]
    result = []
    for group in grouped.values():
        qty = group["po_qty"]
        group["unit_cost"] = group.pop("po_amount") / qty if abs(qty) > EPS else 0
        group["variance_pct"] = (group["variance_qty"] / qty * 100) if qty else 0
        result.append(group)
    return result

def execute(filters=None):
    filters = frappe._dict(filters or {})
    currency = _validate(filters)
    rows = get_data(filters, currency)
    summary = [
        {"label": _("Total PO Qty"), "value": sum(r["po_qty"] for r in rows),
         "datatype": "Float", "indicator": "Blue"},
        {"label": _("Total Receipt Qty"), "value": sum(r["receipt_qty"] for r in rows),
         "datatype": "Float", "indicator": "Blue"},
        {"label": _("Discount-Eligible Excess Qty"),
         "value": sum(r["eligible_excess_qty"] for r in rows),
         "datatype": "Float", "indicator": "Orange"},
        {"label": _("Estimated Excess Discount"),
         "value": sum(r["discount_value"] for r in rows),
         "datatype": "Currency", "currency": currency, "indicator": "Green"},
    ]
    return get_columns(), rows, None, None, summary


def _size_labels(codes):
    """Resolve size abbreviations from Item Attribute master, not item codes.

    Attribute Value stores the full label on the Item; Item Attribute Value
    stores its matching 'abbr' on the corresponding Item Attribute parent.
    """
    size_values = {}
    for batch in _chunks(sorted(codes)):
        for row in frappe.get_all(
            "Item Variant Attribute",
            filters={"parent": ["in", batch]},
            fields=["parent", "attribute", "attribute_value"],
            limit_page_length=0,
        ):
            if "size" in (row.attribute or "").lower() and row.attribute_value:
                size_values[row.parent] = (row.attribute, row.attribute_value)
    if not size_values:
        return {}
    attributes = {key[0] for key in size_values.values()}
    abbreviations = {}
    for batch in _chunks(sorted(attributes)):
        for value in frappe.get_all(
            "Item Attribute Value",
            filters={"parent": ["in", batch]},
            fields=["parent", "attribute_value", "abbr"],
            limit_page_length=0,
        ):
            if value.abbr:
                abbreviations[(value.parent, value.attribute_value)] = value.abbr
    return {
        code: abbreviations.get(pair) or pair[1]
        for code, pair in size_values.items()
    }


def build_matrix(rows, sizes, images):
    """Pure presentation rollup. All financial logic is already per variant."""
    by_template = defaultdict(list)
    for row in rows:
        by_template[row["item_template"]].append(row)
    blocks = []
    for template, items in sorted(by_template.items()):
        used = set()
        cells = []
        for row in sorted(items, key=lambda v: (str(sizes.get(v["item_code"]) or ""), v["item_code"])):
            code = row["item_code"]
            label = str(sizes.get(code) or code)
            if label in used:
                label = f"{label} ({code})"
            used.add(label)
            cells.append({"label": label, "item_code": code, **{
                key: row[key] for key in (
                    "po_qty", "receipt_qty", "variance_qty", "variance_pct",
                    "tolerance_qty", "eligible_excess_qty", "unit_cost", "discount_value"
                )
            }})
        totals = {key: sum(flt(row[key]) for row in items) for key in (
            "po_qty", "receipt_qty", "variance_qty", "tolerance_qty",
            "eligible_excess_qty", "discount_value"
        )}
        totals["variance_pct"] = (totals["variance_qty"] / totals["po_qty"] * 100
                                  if totals["po_qty"] else 0)
        totals["unit_cost"] = (sum(flt(row["po_qty"]) * flt(row["unit_cost"])
                                   for row in items) / totals["po_qty"]
                               if totals["po_qty"] else 0)
        blocks.append({"item_code": template, "image": images.get(template),
                       "variants": cells, "totals": totals})
    return blocks


@frappe.whitelist()
def get_matrix_data(company, supplier, item_year=None, season=None,
                    collection=None, discount_pct=50,
                    tolerance_pct=DEFAULT_TOLERANCE_PCT,
                    report_currency="CNY"):
    """Read-only matrix endpoint; mirrors the report permission and filter checks."""
    filters = frappe._dict(company=company, supplier=supplier,
                           item_year=item_year, season=season,
                           collection=collection, discount_pct=discount_pct,
                           tolerance_pct=tolerance_pct,
                           report_currency=report_currency,
                           view_level="Item Variant")
    currency = _validate(filters)
    rows = get_data(filters, currency)
    codes = {row["item_code"] for row in rows}
    templates = {row["item_template"] for row in rows}
    images = {}
    for batch in _chunks(sorted(codes | templates)):
        for item in frappe.get_all("Item", filters={"name": ["in", batch]},
                                   fields=["name", "image"], limit_page_length=0):
            if item.image:
                images[item.name] = item.image
    for row in rows:
        template = row["item_template"]
        if template not in images and images.get(row["item_code"]):
            images[template] = images[row["item_code"]]
    return {"currency": currency, "tolerance_pct": filters["tolerance_pct"],
            "discount_pct": filters["discount_pct"],
            "blocks": build_matrix(rows, _size_labels(codes), images)}

