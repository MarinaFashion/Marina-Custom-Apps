from collections import defaultdict
from datetime import timedelta

import frappe
from frappe.utils import cint, flt, getdate, today

from marina_custom_apps.stock_transfer_audit.control_service import (
    get_open_transit_rows,
    get_settings,
    get_variance_value_maps,
)


_CACHE_KEY = "marina:stock_transfer_audit:kpis:v017"
_CACHE_SECONDS = 300


def _metrics():
    cached = frappe.cache.get_value(_CACHE_KEY)
    if cached:
        return frappe._dict(cached)

    settings = get_settings()
    open_rows = get_open_transit_rows()

    pending = frappe.get_all(
        "Stock Transfer Audit Record",
        filters={"docstatus": 1, "processing_status": "Pending"},
        fields=["name"],
        limit_page_length=0,
    )

    window_days = max(cint(settings.kpi_window_days), 1)
    cutoff = getdate(today()) - timedelta(days=window_days - 1)

    records = frappe.get_all(
        "Stock Transfer Audit Record",
        filters={"docstatus": ["in", [1, 2]], "audit_result": "Variance"},
        fields=["name", "receive_stock", "total_abs_variance_qty"],
        limit_page_length=0,
    )

    receive_names = [r.receive_stock for r in records if r.receive_stock]
    dates = {}
    if receive_names:
        dates = {
            r.name: getdate(r.posting_date)
            for r in frappe.get_all(
                "Stock Entry",
                filters={"name": ["in", receive_names]},
                fields=["name", "posting_date"],
                limit_page_length=0,
            )
        }

    selected = [
        r for r in records if r.receive_stock and dates.get(r.receive_stock) and dates[r.receive_stock] >= cutoff
    ]
    selected_names = [r.name for r in selected]
    values, ignored_values = get_variance_value_maps(selected_names)

    ignored_qty = defaultdict(float)
    if selected_names:
        for row in frappe.get_all(
            "Stock Transfer Audit Item",
            filters={
                "parent": ["in", selected_names],
                "parenttype": "Stock Transfer Audit Record",
                "action": "Ignore",
            },
            fields=["parent", "discrepancy_qty"],
            limit_page_length=0,
        ):
            ignored_qty[row.parent] += abs(flt(row.discrepancy_qty))

    metrics = {
        "open_transit_count": len(open_rows),
        "overdue_transit_count": sum(
            1 for row in open_rows if row.aging_status in ("Overdue", "Critical")
        ),
        "critical_transit_count": sum(
            1 for row in open_rows if row.aging_status == "Critical"
        ),
        "qty_in_transit": sum(flt(row.qty_sent) for row in open_rows),
        "value_in_transit": sum(flt(row.stock_value) for row in open_rows),
        "pending_audits": len(pending),
        "variance_qty": sum(flt(r.total_abs_variance_qty) for r in selected),
        "variance_value": sum(flt(values.get(r.name)) for r in selected),
        "ignored_qty": sum(flt(ignored_qty.get(r.name)) for r in selected),
        "ignored_value": sum(flt(ignored_values.get(r.name)) for r in selected),
    }

    frappe.cache.set_value(_CACHE_KEY, metrics, expires_in_sec=_CACHE_SECONDS)
    return frappe._dict(metrics)


def _card(value, fieldtype, route):
    return {
        "value": value,
        "fieldtype": fieldtype,
        "route": ["query-report", route],
    }


@frappe.whitelist()
def open_transit_count():
    return _card(_metrics().open_transit_count, "Int", "Stock Transfer Open Transit Aging")


@frappe.whitelist()
def overdue_transit_count():
    return _card(_metrics().overdue_transit_count, "Int", "Stock Transfer Open Transit Aging")


@frappe.whitelist()
def critical_transit_count():
    return _card(_metrics().critical_transit_count, "Int", "Stock Transfer Open Transit Aging")


@frappe.whitelist()
def qty_in_transit():
    return _card(_metrics().qty_in_transit, "Float", "Stock Transfer Open Transit Aging")


@frappe.whitelist()
def value_in_transit():
    return _card(_metrics().value_in_transit, "Currency", "Stock Transfer Open Transit Aging")


@frappe.whitelist()
def pending_audits():
    return _card(_metrics().pending_audits, "Int", "Stock Transfer Pending Audit Variance")


@frappe.whitelist()
def variance_value():
    return _card(_metrics().variance_value, "Currency", "Stock Transfer Variance Summary")


@frappe.whitelist()
def ignored_variance_qty():
    return _card(_metrics().ignored_qty, "Float", "Stock Transfer Ignore Analysis")
