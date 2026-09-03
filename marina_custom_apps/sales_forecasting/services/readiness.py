import frappe
from frappe.utils import flt

from .common import safe_field, settings


def refresh_buying_plan(plan_name, *, commit=True):
    cfg = settings()
    plan = frappe.get_doc("Forecast Buying Plan", plan_name)
    if not plan.items:
        return {"rows": 0}

    item_year = safe_field(cfg.item_year_field, "item_year")
    item_season = safe_field(cfg.item_season_field, "season")
    item_collection = safe_field(cfg.item_collection_field, "collection")
    item_drop = safe_field(cfg.item_drop_field, "custom_drop")
    item_display = safe_field(cfg.item_display_date_field, "display_date")
    item_group = safe_field(cfg.item_main_group_field, "custom_item_main_group")
    supplier = cfg.buying_supplier or "Midmak"
    price_list = cfg.selling_price_list or "Standard Selling"

    for row in plan.items:
        params = [
            str(plan.plan_year), plan.season, row.collection, row.drop,
            str(row.display_date), row.main_group,
        ]
        where = f"""
            i.`{item_year}` = %s
            and i.`{item_season}` = %s
            and i.`{item_collection}` = %s
            and i.`{item_drop}` = %s
            and i.`{item_display}` = %s
            and i.`{item_group}` = %s
            and i.disabled = 0
        """

        styles_created = frappe.db.sql(
            f"""
            select count(distinct coalesce(nullif(i.variant_of, ''), i.name))
            from `tabItem` i
            where {where}
            """,
            params,
        )[0][0] or 0

        styles_priced = frappe.db.sql(
            f"""
            select count(distinct coalesce(nullif(i.variant_of, ''), i.name))
            from `tabItem` i
            where {where}
              and exists (
                  select 1
                  from `tabItem Price` ip
                  where ip.item_code = i.name
                    and ip.selling = 1
                    and ip.price_list = %s
                    and ip.price_list_rate > 0
                    and (ip.valid_from is null or ip.valid_from <= %s)
              )
            """,
            [*params, price_list, str(row.display_date)],
        )[0][0] or 0

        po = frappe.db.sql(
            f"""
            select coalesce(sum(poi.qty), 0) as po_qty,
                   coalesce(sum(poi.received_qty), 0) as received_qty
            from `tabPurchase Order Item` poi
            inner join `tabPurchase Order` po on po.name = poi.parent
            inner join `tabItem` i on i.name = poi.item_code
            where po.docstatus = 1
              and po.supplier = %s
              and {where}
            """,
            [supplier, *params],
            as_dict=True,
        )[0]

        updates = {
            "styles_created": int(styles_created),
            "styles_priced": int(styles_priced),
            "po_qty": flt(po.po_qty),
            "received_qty": flt(po.received_qty),
        }
        planned_styles = flt(row.planned_styles)
        planned_qty = flt(row.planned_total_qty)
        updates.update({
            "assortment_readiness_pct": min(100, flt(styles_created) / planned_styles * 100) if planned_styles else 0,
            "price_readiness_pct": min(100, flt(styles_priced) / max(flt(styles_created), 1) * 100) if styles_created else 0,
            "po_completion_pct": min(100, flt(po.po_qty) / planned_qty * 100) if planned_qty else 0,
            "receipt_completion_pct": min(100, flt(po.received_qty) / planned_qty * 100) if planned_qty else 0,
        })
        frappe.db.set_value("Forecast Buying Plan Item", row.name, updates, update_modified=False)
        for field, value in updates.items():
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
    return {"rows": len(plan.items), **parent_updates}
