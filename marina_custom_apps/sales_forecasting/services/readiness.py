from collections import defaultdict

import frappe
from frappe.utils import flt

from .common import safe_field, settings


QUERY_BATCH_SIZE = 800


def refresh_buying_plan(plan_name, *, commit=True):
    """Refresh ERP buying readiness at Year + Season + Main Group grain.

    Collection, Drop and Display Date remain Buying Plan / forecast-timing dimensions,
    but they are intentionally not used to decide whether seasonal merchandise has
    been created, ordered or received.
    """
    cfg = settings()
    plan = frappe.get_doc("Forecast Buying Plan", plan_name)
    if not plan.items:
        return {"rows": 0}

    item_year = safe_field(cfg.item_year_field, "item_year")
    item_season = safe_field(cfg.item_season_field, "season")
    item_group = safe_field(cfg.item_main_group_field, "custom_item_main_group")
    price_list = cfg.selling_price_list or "Standard Selling"

    grouped = defaultdict(lambda: {
        "planned_styles": 0.0,
        "planned_qty": 0.0,
        "rows": [],
    })
    for row in plan.items:
        group = (row.main_group or "").strip()
        grouped[group]["planned_styles"] += flt(row.planned_styles)
        grouped[group]["planned_qty"] += flt(row.planned_total_qty)
        grouped[group]["rows"].append(row)

    group_readiness = []
    for group, bucket in grouped.items():
        progress = _load_group_progress(
            company=plan.company,
            plan_year=plan.plan_year,
            season=plan.season,
            main_group=group,
            item_year=item_year,
            item_season=item_season,
            item_group=item_group,
            price_list=price_list,
        )
        planned_styles = flt(bucket["planned_styles"])
        planned_qty = flt(bucket["planned_qty"])
        progress.update({
            "main_group": group,
            "planned_styles": planned_styles,
            "planned_qty": planned_qty,
            "assortment_readiness_pct": (
                min(100, flt(progress["styles_created"]) / planned_styles * 100)
                if planned_styles else 0
            ),
            "price_readiness_pct": (
                min(100, flt(progress["styles_priced"]) / max(flt(progress["styles_created"]), 1) * 100)
                if progress["styles_created"] else 0
            ),
            "po_completion_pct": (
                min(100, flt(progress["po_qty"]) / planned_qty * 100)
                if planned_qty else 0
            ),
            "receipt_completion_pct": (
                min(100, flt(progress["received_qty"]) / planned_qty * 100)
                if planned_qty else 0
            ),
        })
        group_readiness.append(progress)

        # Row-level progress from v0.43.2 is hidden but retained for schema compatibility.
        # Put each Main Group total on one representative row so the existing parent
        # calculation can aggregate season totals without counting the same readiness
        # once per Collection/Drop/Display Date row.
        for index, row in enumerate(bucket["rows"]):
            values = (
                {
                    "styles_created": int(progress["styles_created"]),
                    "styles_priced": int(progress["styles_priced"]),
                    "po_qty": flt(progress["po_qty"]),
                    "received_qty": flt(progress["received_qty"]),
                }
                if index == 0
                else {
                    "styles_created": 0,
                    "styles_priced": 0,
                    "po_qty": 0,
                    "received_qty": 0,
                }
            )
            values.update({
                "assortment_readiness_pct": 0,
                "price_readiness_pct": 0,
                "po_completion_pct": 0,
                "receipt_completion_pct": 0,
            })
            frappe.db.set_value(
                "Forecast Buying Plan Item",
                row.name,
                values,
                update_modified=False,
            )
            for field, value in values.items():
                row.set(field, value)

    plan._calculate_plan()
    parent_updates = {
        "total_styles": plan.total_styles,
        "total_qty": plan.total_qty,
        "total_cost": plan.total_cost,
        "total_selling_value": plan.total_selling_value,
        "selling_value_ex_vat": plan.selling_value_ex_vat,
        "planned_gross_profit": plan.planned_gross_profit,
        "planned_margin_pct": plan.planned_margin_pct,
        "styles_created": plan.styles_created,
        "styles_priced": plan.styles_priced,
        "po_qty": plan.po_qty,
        "received_qty": plan.received_qty,
        "assortment_readiness_pct": plan.assortment_readiness_pct,
        "po_completion_pct": plan.po_completion_pct,
        "receipt_completion_pct": plan.receipt_completion_pct,
    }
    frappe.db.set_value("Forecast Buying Plan", plan.name, parent_updates, update_modified=True)
    if commit:
        frappe.db.commit()

    return {
        "rows": len(plan.items),
        "group_readiness": group_readiness,
        **parent_updates,
    }


def _load_group_progress(
    *,
    company,
    plan_year,
    season,
    main_group,
    item_year,
    item_season,
    item_group,
    price_list,
):
    items = _matching_items(
        plan_year=plan_year,
        season=season,
        main_group=main_group,
        item_year=item_year,
        item_season=item_season,
        item_group=item_group,
    )
    if not items:
        return {
            "styles_created": 0,
            "styles_priced": 0,
            "po_qty": 0,
            "received_qty": 0,
        }

    active_items = [row for row in items if not int(row.disabled or 0)]
    active_styles = {row.style_key for row in active_items if row.style_key}
    all_item_codes = [row.item_code for row in items if row.item_code]

    styles_created = len(active_styles)
    styles_priced = _count_priced_styles(active_items, price_list)
    po_qty = _sum_purchase_order_qty(all_item_codes, company)
    received_qty = _sum_purchase_receipt_qty(all_item_codes, company)

    return {
        "styles_created": int(styles_created),
        "styles_priced": int(styles_priced),
        "po_qty": flt(po_qty),
        "received_qty": flt(received_qty),
    }


def _matching_items(*, plan_year, season, main_group, item_year, item_season, item_group):
    where = _classification_where(
        "i", "template", item_year, item_season, item_group
    )
    return frappe.db.sql(
        f"""
        select
            i.name as item_code,
            coalesce(nullif(i.variant_of, ''), i.name) as style_key,
            i.disabled
        from `tabItem` i
        left join `tabItem` template on template.name = i.variant_of
        where {where}
        """,
        [str(plan_year), season, main_group],
        as_dict=True,
    )


def _count_priced_styles(items, price_list):
    if not items:
        return 0

    code_to_style = {}
    candidate_codes = set()
    for row in items:
        if row.item_code:
            code_to_style[row.item_code] = row.style_key
            candidate_codes.add(row.item_code)
        if row.style_key:
            code_to_style[row.style_key] = row.style_key
            candidate_codes.add(row.style_key)

    priced_styles = set()
    for batch in _chunks(sorted(candidate_codes), QUERY_BATCH_SIZE):
        placeholders = ",".join(["%s"] * len(batch))
        rows = frappe.db.sql(
            f"""
            select distinct ip.item_code
            from `tabItem Price` ip
            where ip.item_code in ({placeholders})
              and ip.selling = 1
              and ip.price_list = %s
              and ip.price_list_rate > 0
            """,
            [*batch, price_list],
            as_dict=True,
        )
        for row in rows:
            style = code_to_style.get(row.item_code)
            if style:
                priced_styles.add(style)
    return len(priced_styles)


def _sum_purchase_order_qty(item_codes, company):
    return _sum_transaction_qty(
        item_codes=item_codes,
        company=company,
        child_table="Purchase Order Item",
        child_alias="poi",
        parent_table="Purchase Order",
        parent_alias="po",
    )


def _sum_purchase_receipt_qty(item_codes, company):
    # Purchase Invoice is deliberately not receipt evidence. Readiness follows the
    # physical supply chain, so Received Qty comes directly from submitted receipts.
    return _sum_transaction_qty(
        item_codes=item_codes,
        company=company,
        child_table="Purchase Receipt Item",
        child_alias="pri",
        parent_table="Purchase Receipt",
        parent_alias="pr",
    )


def _sum_transaction_qty(*, item_codes, company, child_table, child_alias, parent_table, parent_alias):
    if not item_codes:
        return 0

    total = 0.0
    for batch in _chunks(sorted(set(item_codes)), QUERY_BATCH_SIZE):
        placeholders = ",".join(["%s"] * len(batch))
        total += flt(frappe.db.sql(
            f"""
            select coalesce(sum({child_alias}.qty), 0)
            from `tab{child_table}` {child_alias}
            inner join `tab{parent_table}` {parent_alias}
                on {parent_alias}.name = {child_alias}.parent
            where {parent_alias}.docstatus = 1
              and {parent_alias}.company = %s
              and {child_alias}.item_code in ({placeholders})
            """,
            [company, *batch],
        )[0][0] or 0)
    return total


def _classification_where(item_alias, template_alias, item_year, item_season, item_group):
    return f"""
        {_resolved_text(item_alias, template_alias, item_year)} = %s
        and {_resolved_text(item_alias, template_alias, item_season)} = %s
        and {_resolved_text(item_alias, template_alias, item_group)} = %s
    """


def _resolved_text(item_alias, template_alias, fieldname):
    """Use the variant value, falling back to its Item Template when blank."""
    return (
        f"coalesce("
        f"nullif(cast({item_alias}.`{fieldname}` as char), ''), "
        f"nullif(cast({template_alias}.`{fieldname}` as char), '')"
        f")"
    )


def _chunks(values, size):
    for index in range(0, len(values), size):
        yield values[index:index + size]
