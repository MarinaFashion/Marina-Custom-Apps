import frappe

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
from marina_custom_apps.stock_transfer_control.services.warehouse_policy import (
    get_physical_for_transit,
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
    if role in {
        ROLE_ADMINISTRATOR,
        ROLE_STOCK_MANAGER,
        ROLE_WAREHOUSE_MANAGER,
    }:
        manual_types.append(TYPE_TRANSFER_BETWEEN)

    return {
        "role": role,
        "manual_types": manual_types,
        "allowed_sources": allowed_sources,
    }


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

        # Source mapping must itself be valid before this source can send.
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
    validate_transit_warehouse(transit_warehouse)
    return get_physical_for_transit(transit_warehouse)
