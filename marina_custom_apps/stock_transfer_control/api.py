import json

import frappe
from frappe import _

from marina_custom_apps.stock_transfer_control.constants import (
    ROLE_ADMINISTRATOR,
    ROLE_SALES_SUPERVISOR,
    ROLE_STOCK_MANAGER,
    ROLE_WAREHOUSE_MANAGER,
    TYPE_SEND_STOCK,
    TYPE_TRANSFER_BETWEEN,
)
from marina_custom_apps.stock_transfer_control.services.role_policy import (
    get_allowed_physical_warehouses,
    get_effective_transfer_role,
)
from marina_custom_apps.stock_transfer_control.services.transfer_policy import validate_send_stock_route
from marina_custom_apps.stock_transfer_control.services.warehouse_policy import (
    validate_physical_warehouse,
    validate_transit_warehouse,
)


@frappe.whitelist()
def get_transfer_context():
    role = get_effective_transfer_role()
    allowed_sources = []
    if role in {ROLE_SALES_SUPERVISOR, ROLE_WAREHOUSE_MANAGER}:
        allowed_sources = get_allowed_physical_warehouses()

    manual_types = [TYPE_SEND_STOCK]
    if role in {ROLE_ADMINISTRATOR, ROLE_STOCK_MANAGER, ROLE_WAREHOUSE_MANAGER}:
        manual_types.append(TYPE_TRANSFER_BETWEEN)

    return {"role": role, "manual_types": manual_types, "allowed_sources": allowed_sources}


@frappe.whitelist()
def get_valid_sources(stock_entry_type):
    role = get_effective_transfer_role()
    if stock_entry_type not in {TYPE_SEND_STOCK, TYPE_TRANSFER_BETWEEN}:
        return []
    if role in {ROLE_SALES_SUPERVISOR, ROLE_WAREHOUSE_MANAGER}:
        return get_allowed_physical_warehouses()
    if role not in {ROLE_ADMINISTRATOR, ROLE_STOCK_MANAGER}:
        return []

    rows = frappe.get_all(
        "Warehouse",
        filters={"disabled": 0},
        fields=["name", "warehouse_type"],
        order_by="name asc",
        limit_page_length=0,
    )
    if stock_entry_type == TYPE_SEND_STOCK:
        return [row.name for row in rows if row.warehouse_type != "Transit"]
    return [row.name for row in rows]


@frappe.whitelist()
def get_valid_targets(stock_entry_type, source_warehouse=None):
    if not source_warehouse:
        return []

    role = get_effective_transfer_role()

    if stock_entry_type == TYPE_SEND_STOCK:
        source = validate_physical_warehouse(source_warehouse)
        if not source.default_in_transit_warehouse:
            return []
        validate_transit_warehouse(source.default_in_transit_warehouse)

        rows = frappe.get_all(
            "Warehouse",
            filters={
                "disabled": 0,
                "warehouse_type": "Transit",
                "company": source.company,
                "name": ["!=", source.default_in_transit_warehouse],
            },
            fields=["name"],
            order_by="name asc",
            limit_page_length=0,
        )
        valid = []
        for row in rows:
            try:
                validate_transit_warehouse(row.name)
            except Exception:
                continue
            valid.append(row.name)
        return valid

    if stock_entry_type == TYPE_TRANSFER_BETWEEN:
        source = frappe.db.get_value(
            "Warehouse",
            source_warehouse,
            ["company", "warehouse_type", "disabled"],
            as_dict=True,
        )
        if not source or source.disabled:
            return []

        rows = frappe.get_all(
            "Warehouse",
            filters={
                "disabled": 0,
                "company": source.company,
                "name": ["!=", source_warehouse],
            },
            fields=["name", "warehouse_type"],
            order_by="name asc",
            limit_page_length=0,
        )

        if role in {ROLE_ADMINISTRATOR, ROLE_STOCK_MANAGER}:
            valid = []
            for row in rows:
                if row.warehouse_type == "Transit":
                    try:
                        validate_transit_warehouse(row.name)
                    except Exception:
                        continue
                valid.append(row.name)
            return valid

        if role == ROLE_WAREHOUSE_MANAGER:
            return [row.name for row in rows if row.warehouse_type != "Transit"]

    return []


@frappe.whitelist()
def derive_intended_final_warehouse(transit_warehouse):
    if not transit_warehouse:
        return None
    _transit, physical = validate_transit_warehouse(transit_warehouse)
    return physical


@frappe.whitelist()
def get_material_request_stock_entry_route(material_requests):
    if isinstance(material_requests, str):
        try:
            material_requests = json.loads(material_requests)
        except ValueError:
            material_requests = [material_requests]

    names = sorted({name for name in (material_requests or []) if name})
    if not names:
        frappe.throw(_("At least one Material Request is required."))

    routes = set()
    dispatch_runs = set()
    final_stores = set()
    instructions = set()

    for mr_name in names:
        mr = frappe.db.get_value(
            "Material Request",
            mr_name,
            [
                "name", "docstatus", "set_from_warehouse", "set_warehouse",
                "custom_dc_dispatch_run", "custom_final_store_warehouse",
                "custom_dc_dispatch_instructions",
            ],
            as_dict=True,
        )
        if not mr:
            frappe.throw(_("Material Request {0} does not exist.").format(mr_name))
        if mr.docstatus != 1:
            frappe.throw(_("Material Request {0} must be submitted.").format(mr_name))

        if mr.custom_dc_dispatch_run:
            dispatch_runs.add(mr.custom_dc_dispatch_run)
        if mr.custom_final_store_warehouse:
            final_stores.add(mr.custom_final_store_warehouse)
        if mr.custom_dc_dispatch_instructions:
            instructions.add(mr.custom_dc_dispatch_instructions)

        rows = frappe.get_all(
            "Material Request Item",
            filters={"parent": mr_name},
            fields=["from_warehouse", "warehouse"],
            limit_page_length=0,
        ) or [frappe._dict()]

        for row in rows:
            source = row.from_warehouse or mr.set_from_warehouse
            target = row.warehouse or mr.set_warehouse
            if not source or not target:
                frappe.throw(
                    _("Material Request {0} does not provide a complete warehouse route.").format(mr_name)
                )
            routes.add((source, target))

    if len(routes) != 1:
        frappe.throw(_("The selected Material Request(s) contain more than one warehouse route."))

    source, target = next(iter(routes))
    intended_final = validate_send_stock_route(source, target)

    result = {
        "stock_entry_type": TYPE_SEND_STOCK,
        "from_warehouse": source,
        "to_warehouse": target,
        "intended_final_warehouse": intended_final,
    }
    if len(dispatch_runs) == 1:
        result["dc_dispatch_run"] = next(iter(dispatch_runs))
    if len(final_stores) == 1:
        result["final_store_warehouse"] = next(iter(final_stores))
    if len(instructions) == 1:
        result["dc_dispatch_instructions"] = next(iter(instructions))
    return result
