import frappe
from frappe import _

from marina_custom_apps.stock_transfer_control.constants import (
    ROLE_ADMINISTRATOR,
    ROLE_SALES_SUPERVISOR,
    ROLE_STOCK_MANAGER,
    ROLE_WAREHOUSE_MANAGER,
    TYPE_RECEIVE_STOCK,
    TYPE_SEND_STOCK,
    TYPE_TRANSFER_BETWEEN,
)
from marina_custom_apps.stock_transfer_control.services.role_policy import (
    get_allowed_physical_warehouses,
    get_effective_transfer_role,
)
from marina_custom_apps.stock_transfer_control.services.warehouse_policy import (
    get_physical_for_transit,
    get_warehouse_info,
    validate_physical_transit_pair,
    validate_physical_warehouse,
    validate_transit_warehouse,
)


def classify_route(source_warehouse, target_warehouse):
    source = get_warehouse_info(source_warehouse)
    target = get_warehouse_info(target_warehouse)

    if source.is_transit and target.is_transit:
        return "Transit → Transit"
    if source.is_transit and not target.is_transit:
        return "Transit → Physical"
    if not source.is_transit and target.is_transit:
        return "Physical → Transit"
    return "Physical → Physical"


def _assert_different_and_same_company(source, target):
    if source.name == target.name:
        frappe.throw(_("Source and target warehouses must be different."))

    if source.company != target.company:
        frappe.throw(_("Cross-company warehouse transfers are not allowed."))


def _assert_user_source_permission(source_warehouse, user=None):
    role = get_effective_transfer_role(user)

    if role in {ROLE_ADMINISTRATOR, ROLE_STOCK_MANAGER}:
        return

    if role not in {ROLE_SALES_SUPERVISOR, ROLE_WAREHOUSE_MANAGER}:
        frappe.throw(_("You are not authorized to perform Marina stock transfers."))

    allowed = get_allowed_physical_warehouses(user)
    if not allowed:
        target_user = user or frappe.session.user
        frappe.throw(
            _(
                "User {0} has no valid Warehouse Users Allowed records. "
                "Please configure at least one active physical warehouse."
            ).format(target_user)
        )

    if source_warehouse not in allowed:
        frappe.throw(
            _("You are not allowed to use warehouse {0} as the source.").format(
                source_warehouse
            )
        )


def validate_send_stock_route(source_warehouse, target_warehouse, user=None):
    source, target, intended_final = validate_physical_transit_pair(
        source_warehouse,
        target_warehouse,
    )
    _assert_different_and_same_company(source, target)
    _assert_user_source_permission(source_warehouse, user)
    return intended_final


def validate_receive_stock_route(
    source_transit,
    target_physical,
    user=None,
):
    source, linked_physical = validate_transit_warehouse(source_transit)
    target = validate_physical_warehouse(target_physical)
    _assert_different_and_same_company(source, target)

    if linked_physical != target_physical:
        frappe.throw(
            _(
                "Receive Stock target must be the physical warehouse linked "
                "to Transit warehouse {0}."
            ).format(source_transit)
        )

    role = get_effective_transfer_role(user)
    if role in {ROLE_ADMINISTRATOR, ROLE_STOCK_MANAGER}:
        return

    if role not in {ROLE_SALES_SUPERVISOR, ROLE_WAREHOUSE_MANAGER}:
        frappe.throw(_("You are not authorized to receive this stock transfer."))

    allowed = get_allowed_physical_warehouses(user)
    if target_physical not in allowed:
        frappe.throw(
            _(
                "You are not allowed to End Transit into warehouse {0}."
            ).format(target_physical)
        )


def validate_transfer_between_route(source_warehouse, target_warehouse, user=None):
    role = get_effective_transfer_role(user)

    if role in {ROLE_ADMINISTRATOR, ROLE_STOCK_MANAGER}:
        source = get_warehouse_info(source_warehouse)
        target = get_warehouse_info(target_warehouse)

        if not source.is_active or not target.is_active:
            frappe.throw(_("Both warehouses must be active."))

        _assert_different_and_same_company(source, target)

        # Any Transit warehouse involved in a privileged correction transfer
        # must still be fully valid/configured.
        if source.is_transit:
            validate_transit_warehouse(source.name)
        if target.is_transit:
            validate_transit_warehouse(target.name)

        return

    if role != ROLE_WAREHOUSE_MANAGER:
        frappe.throw(_("Transfer Between is not allowed for your role."))

    source = validate_physical_warehouse(source_warehouse)
    target = validate_physical_warehouse(target_warehouse)
    _assert_different_and_same_company(source, target)
    _assert_user_source_permission(source_warehouse, user)


def validate_route_for_type(stock_entry_type, source_warehouse, target_warehouse, user=None):
    if stock_entry_type == TYPE_SEND_STOCK:
        return validate_send_stock_route(source_warehouse, target_warehouse, user=user)

    if stock_entry_type == TYPE_RECEIVE_STOCK:
        return validate_receive_stock_route(source_warehouse, target_warehouse, user=user)

    if stock_entry_type == TYPE_TRANSFER_BETWEEN:
        return validate_transfer_between_route(source_warehouse, target_warehouse, user=user)

    frappe.throw(
        _("Stock Entry Type {0} is not managed by Marina Stock Transfer Control.").format(
            stock_entry_type
        )
    )
