import frappe
from frappe.utils import flt, getdate, nowdate


def _classification(template):
    settings = frappe.get_single("DC Dispatch Settings")
    meta = frappe.get_meta("Item")
    fmap = {
        "item_name": "item_name",
        "item_year": "item_year",
        "season": "season",
        "collection": "collection",
        "drop": "custom_drop",
        "main_group": settings.item_main_group_field,
    }
    valid = [v for v in fmap.values() if v and meta.get_field(v)]
    row = frappe.db.get_value("Item", template, valid, as_dict=True) or {}
    return {k: row.get(v) for k, v in fmap.items() if v in valid}


def _coverage_doc(company, warehouse, template):
    name = frappe.db.get_value(
        "Cycle Count Coverage",
        {
            "company": company,
            "store_warehouse": warehouse,
            "item_template": template,
        },
        "name",
    )
    if name:
        return frappe.get_doc("Cycle Count Coverage", name)

    return frappe.get_doc({
        "doctype": "Cycle Count Coverage",
        "company": company,
        "store_warehouse": warehouse,
        "item_template": template,
        **_classification(template),
    })


def _upsert(company, warehouse, template, values):
    doc = _coverage_doc(company, warehouse, template)
    for fieldname, value in values.items():
        doc.set(fieldname, value)

    if doc.is_new():
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)
    return doc.name


def mark_selected(plan):
    dt = getdate(plan.count_date or nowdate())
    for store in plan.stores:
        for style in plan.styles:
            _upsert(
                plan.company,
                store.warehouse,
                style.item_template,
                {
                    "last_selected_date": dt,
                    "last_cycle_count_plan": plan.name,
                    "last_count_status": "Selected / Pending",
                },
            )


def mark_completed(count):
    grouped = {}

    for row in count.items:
        template = row.item_template or row.item_code
        bucket = grouped.setdefault(template, {
            "net_variance_qty": 0.0,
            "abs_variance_qty": 0.0,
            "variance_value": 0.0,
            "system_qty_abs": 0.0,
            "rows": [],
        })

        variance_qty = flt(row.variance_qty)
        bucket["net_variance_qty"] += variance_qty
        bucket["abs_variance_qty"] += abs(variance_qty)
        bucket["variance_value"] += flt(row.variance_value)
        bucket["system_qty_abs"] += abs(flt(row.system_qty))
        bucket["rows"].append(row)

    count_date = getdate(count.count_completed_on or nowdate())

    for template, bucket in grouped.items():
        coverage = _coverage_doc(count.company, count.warehouse, template)

        existing_keys = {
            (row.store_cycle_count, row.item_code)
            for row in (coverage.variant_history or [])
            if row.store_cycle_count and row.item_code
        }

        # Backward-compatible idempotence:
        # pre-v0.42 Coverage rows have no variant_history, but may already
        # record this Store Cycle Count in last_store_cycle_count.
        already_recorded = (
            coverage.last_store_cycle_count == count.name
            or any(
                store_cycle_count == count.name
                for store_cycle_count, item_code in existing_keys
            )
        )

        denominator = bucket["system_qty_abs"]
        abs_variance = bucket["abs_variance_qty"]
        if denominator:
            accuracy = max(0.0, 100.0 - abs_variance * 100.0 / denominator)
        else:
            accuracy = 100.0 if not abs_variance else 0.0

        current_last_date = (
            getdate(coverage.last_count_date)
            if coverage.last_count_date
            else None
        )
        is_latest = not current_last_date or count_date >= current_last_date

        if not coverage.first_count_date:
            coverage.first_count_date = count_date

        if not already_recorded:
            coverage.number_of_counts = int(coverage.number_of_counts or 0) + 1

        if is_latest:
            coverage.last_count_date = count_date
            coverage.last_cycle_count_plan = count.cycle_count_plan
            coverage.last_store_cycle_count = count.name
            coverage.last_count_status = "Completed"
            coverage.last_variance_qty = bucket["net_variance_qty"]
            coverage.last_variance_value = bucket["variance_value"]
            coverage.last_inventory_accuracy_percent = accuracy

        for row in bucket["rows"]:
            key = (count.name, row.item_code)
            if key in existing_keys:
                continue

            coverage.append("variant_history", {
                "count_date": count_date,
                "store_cycle_count": count.name,
                "item_code": row.item_code,
                "size": row.size,
                "system_qty": flt(row.system_qty),
                "counted_qty": flt(row.counted_qty),
                "variance_qty": flt(row.variance_qty),
                "variance_value": flt(row.variance_value),
            })

        if coverage.is_new():
            coverage.insert(ignore_permissions=True)
        else:
            coverage.save(ignore_permissions=True)
