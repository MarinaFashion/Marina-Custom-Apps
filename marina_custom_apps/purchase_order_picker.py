"""Purchase Order picker query used by Marina purchasing documents.

The standard ERPNext mapper dialog only displays fields passed as setters.
Marina uses Purchase Order.title as the style code / business-facing title,
so this query exposes that field while preserving ERPNext's original filters
and normal user permissions.
"""

import frappe
from frappe.utils import cint


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def search_purchase_orders(
    doctype,
    txt,
    searchfield,
    start,
    page_len,
    filters,
    as_dict=False,
    **kwargs,
):
    if doctype != "Purchase Order":
        return []

    if isinstance(filters, str):
        filters = frappe.parse_json(filters)
    filters = filters or {}

    txt = (txt or "").strip()
    or_filters = []
    if txt:
        value = f"%{txt}%"
        or_filters = [
            ["Purchase Order", "name", "like", value],
            ["Purchase Order", "title", "like", value],
            ["Purchase Order", "supplier", "like", value],
        ]

    rows = frappe.get_list(
        "Purchase Order",
        filters=filters,
        or_filters=or_filters,
        fields=["name", "title", "supplier", "schedule_date"],
        limit_start=start,
        limit_page_length=page_len,
        order_by="modified desc",
    )

    if cint(as_dict):
        return rows

    return [
        [
            row.name,
            row.title or "",
            row.supplier or "",
            row.schedule_date or "",
        ]
        for row in rows
    ]