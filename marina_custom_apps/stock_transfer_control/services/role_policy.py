import frappe

from marina_custom_apps.stock_transfer_control.constants import (
    ROLE_ADMINISTRATOR,
    ROLE_SALES_SUPERVISOR,
    ROLE_STOCK_MANAGER,
    ROLE_WAREHOUSE_MANAGER,
    TRANSFER_ROLE_PRIORITY,
)


def get_effective_transfer_role(user=None):
    """Return Marina's highest effective stock-transfer role for a user."""
    user = user or frappe.session.user

    # Frappe's built-in Administrator account may not carry a literal
    # "Administrator" Role record, so treat the account itself as highest.
    if user == "Administrator":
        return ROLE_ADMINISTRATOR

    roles = set(frappe.get_roles(user))
    for role in TRANSFER_ROLE_PRIORITY:
        if role in roles:
            return role

    return None


def is_privileged_transfer_user(user=None):
    return get_effective_transfer_role(user) in {
        ROLE_ADMINISTRATOR,
        ROLE_STOCK_MANAGER,
    }


def can_use_transfer_between(user=None):
    return get_effective_transfer_role(user) in {
        ROLE_ADMINISTRATOR,
        ROLE_STOCK_MANAGER,
        ROLE_WAREHOUSE_MANAGER,
    }


def requires_allowed_source_warehouse(user=None):
    return get_effective_transfer_role(user) in {
        ROLE_SALES_SUPERVISOR,
        ROLE_WAREHOUSE_MANAGER,
    }


def get_allowed_physical_warehouses(user=None):
    """Return active non-transit warehouses configured for the user.

    Invalid Warehouse Users Allowed rows are ignored by design.
    """
    user = user or frappe.session.user

    rows = frappe.get_all(
        "Warehouse Users Allowed",
        filters={"user": user},
        fields=["warehouse"],
        limit_page_length=0,
    )
    warehouse_names = sorted({row.warehouse for row in rows if row.warehouse})
    if not warehouse_names:
        return []

    warehouses = frappe.get_all(
        "Warehouse",
        filters={
            "name": ["in", warehouse_names],
            "disabled": 0,
            "is_group": 0,
        },
        fields=["name", "warehouse_type", "is_group"],
        limit_page_length=0,
    )

    return sorted(
        row.name
        for row in warehouses
        if row.warehouse_type != "Transit"
    )
