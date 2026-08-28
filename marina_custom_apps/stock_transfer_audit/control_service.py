from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

import frappe
from frappe.utils import cint, date_diff, flt, getdate, today


ROUTE_DC_TO_STORE = "DC to Store"
ROUTE_STORE_TO_STORE = "Store to Store"
ROUTE_STORE_TO_DC = "Store to DC"
ROUTE_OTHER = "Other"


def get_settings():
    try:
        return frappe.get_cached_doc("Stock Transfer Control Settings")
    except frappe.DoesNotExistError:
        return frappe._dict(
            {
                "distribution_center_warehouse": None,
                "dc_to_store_sla_days": 2,
                "store_to_store_sla_days": 2,
                "store_to_dc_sla_days": 2,
                "critical_grace_days": 2,
                "pending_audit_sla_days": 2,
                "large_variance_qty_threshold": 5,
                "large_variance_value_threshold": 1000,
                "kpi_window_days": 30,
                "enable_daily_alerts": 1,
                "alert_role": "Stock Manager",
            }
        )


def classify_transfer(source_warehouse, target_warehouse, settings=None):
    settings = settings or get_settings()
    dc = settings.distribution_center_warehouse

    if not dc:
        return ROUTE_OTHER
    if source_warehouse == dc and target_warehouse != dc:
        return ROUTE_DC_TO_STORE
    if target_warehouse == dc and source_warehouse != dc:
        return ROUTE_STORE_TO_DC
    if source_warehouse != dc and target_warehouse != dc:
        return ROUTE_STORE_TO_STORE
    return ROUTE_OTHER


def get_sla_days(route, settings=None):
    settings = settings or get_settings()
    mapping = {
        ROUTE_DC_TO_STORE: cint(settings.dc_to_store_sla_days),
        ROUTE_STORE_TO_STORE: cint(settings.store_to_store_sla_days),
        ROUTE_STORE_TO_DC: cint(settings.store_to_dc_sla_days),
    }
    return max(mapping.get(route, cint(settings.store_to_store_sla_days) or 2), 0)


def get_aging_status(age_days, sla_days, critical_grace_days):
    age_days = max(cint(age_days), 0)
    sla_days = max(cint(sla_days), 0)
    grace = max(cint(critical_grace_days), 0)

    if age_days > sla_days + grace:
        return "Critical"
    if age_days > sla_days:
        return "Overdue"
    if age_days >= max(sla_days - 1, 0):
        return "Due Soon"
    return "Open"


def get_usernames(user_ids):
    user_ids = list({u for u in user_ids if u})
    if not user_ids:
        return {}

    rows = frappe.get_all(
        "User",
        filters={"name": ["in", user_ids]},
        fields=["name", "username"],
        limit_page_length=0,
    )
    return {row.name: (row.username or row.name) for row in rows}


def get_open_transit_rows(company=None):
    filters = {"docstatus": 1, "stock_entry_type": "Send Stock"}
    if company:
        filters["company"] = company

    sends = frappe.get_list(
        "Stock Entry",
        filters=filters,
        fields=[
            "name",
            "company",
            "posting_date",
            "from_warehouse",
            "to_warehouse",
            "custom_intended_final_warehouse",
            "owner",
        ],
        order_by="posting_date asc, creation asc",
        limit_page_length=0,
    )
    if not sends:
        return []

    names = [row.name for row in sends]

    received = set(
        frappe.get_all(
            "Stock Entry",
            filters={
                "docstatus": 1,
                "stock_entry_type": "Receive Stock",
                "outgoing_stock_entry": ["in", names],
            },
            pluck="outgoing_stock_entry",
            limit_page_length=0,
        )
    )

    drafts = frappe.get_all(
        "Stock Entry",
        filters={
            "docstatus": 0,
            "stock_entry_type": "Receive Stock",
            "outgoing_stock_entry": ["in", names],
        },
        fields=["name", "outgoing_stock_entry"],
        order_by="creation desc",
        limit_page_length=0,
    )
    draft_by_send = {}
    for row in drafts:
        draft_by_send.setdefault(row.outgoing_stock_entry, row.name)

    details = frappe.get_all(
        "Stock Entry Detail",
        filters={"parent": ["in", names], "parenttype": "Stock Entry"},
        fields=["parent", "qty", "basic_rate"],
        limit_page_length=0,
    )

    qty_by_send = defaultdict(float)
    value_by_send = defaultdict(float)
    for row in details:
        qty_by_send[row.parent] += flt(row.qty)
        value_by_send[row.parent] += flt(row.qty) * flt(row.basic_rate)

    settings = get_settings()
    current_date = getdate(today())
    result = []

    for row in sends:
        if row.name in received:
            continue

        target = row.custom_intended_final_warehouse
        route = classify_transfer(row.from_warehouse, target, settings)
        sla = get_sla_days(route, settings)
        age = max(date_diff(current_date, getdate(row.posting_date)), 0)

        result.append(
            frappe._dict(
                {
                    "send_stock": row.name,
                    "company": row.company,
                    "posting_date": row.posting_date,
                    "source_warehouse": row.from_warehouse,
                    "transit_warehouse": row.to_warehouse,
                    "target_warehouse": target,
                    "transfer_route": route,
                    "sla_days": sla,
                    "age_days": age,
                    "aging_status": get_aging_status(
                        age, sla, settings.critical_grace_days
                    ),
                    "qty_sent": qty_by_send[row.name],
                    "stock_value": value_by_send[row.name],
                    "receive_draft": draft_by_send.get(row.name),
                    "owner": row.owner,
                }
            )
        )

    return result


def get_variance_value_maps(record_names):
    record_names = list({name for name in record_names if name})
    if not record_names:
        return {}, {}

    items = frappe.get_all(
        "Stock Transfer Audit Item",
        filters={
            "parent": ["in", record_names],
            "parenttype": "Stock Transfer Audit Record",
        },
        fields=[
            "parent",
            "item_code",
            "discrepancy_qty",
            "action",
            "send_stock_detail",
        ],
        limit_page_length=0,
    )

    send_detail_names = list({r.send_stock_detail for r in items if r.send_stock_detail})
    rate_by_detail = {}
    if send_detail_names:
        rate_by_detail = {
            r.name: flt(r.basic_rate)
            for r in frappe.get_all(
                "Stock Entry Detail",
                filters={"name": ["in", send_detail_names]},
                fields=["name", "basic_rate"],
                limit_page_length=0,
            )
        }

    missing_items = {
        r.item_code
        for r in items
        if r.item_code and (not r.send_stock_detail or r.send_stock_detail not in rate_by_detail)
    }
    rate_by_item = {}
    if missing_items:
        rate_by_item = {
            r.name: flt(r.valuation_rate)
            for r in frappe.get_all(
                "Item",
                filters={"name": ["in", list(missing_items)]},
                fields=["name", "valuation_rate"],
                limit_page_length=0,
            )
        }

    total_value = defaultdict(float)
    ignored_value = defaultdict(float)

    for row in items:
        rate = rate_by_detail.get(row.send_stock_detail)
        if rate is None:
            rate = rate_by_item.get(row.item_code, 0)

        value = abs(flt(row.discrepancy_qty)) * flt(rate)
        total_value[row.parent] += value
        if row.action == "Ignore":
            ignored_value[row.parent] += value

    return dict(total_value), dict(ignored_value)


def get_receive_owner_maps(receive_names):
    receive_names = list({name for name in receive_names if name})
    if not receive_names:
        return {}, {}

    rows = frappe.get_all(
        "Stock Entry",
        filters={"name": ["in", receive_names]},
        fields=["name", "owner"],
        limit_page_length=0,
    )
    owner_by_receive = {row.name: row.owner for row in rows}
    usernames = get_usernames(owner_by_receive.values())
    username_by_receive = {
        name: usernames.get(owner, owner) for name, owner in owner_by_receive.items()
    }
    return owner_by_receive, username_by_receive
