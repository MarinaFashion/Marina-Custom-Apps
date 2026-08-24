from dataclasses import dataclass

import frappe
from frappe import _

from marina_custom_apps.stock_transfer_control.constants import (
    TRANSIT_PREFIX,
    WAREHOUSE_TRANSIT_TYPE,
)


@dataclass(frozen=True)
class WarehouseInfo:
    name: str
    company: str | None
    disabled: int
    warehouse_type: str | None
    default_in_transit_warehouse: str | None
    custom_is_store: int
    custom_is_distribution_center: int
    custom_is_transit: int

    @property
    def is_active(self):
        return not bool(self.disabled)

    @property
    def is_transit(self):
        return self.warehouse_type == WAREHOUSE_TRANSIT_TYPE


def get_warehouse_info(warehouse_name):
    fields = [
        "name",
        "company",
        "disabled",
        "warehouse_type",
        "default_in_transit_warehouse",
    ]

    meta = frappe.get_meta("Warehouse")
    for optional in (
        "custom_is_store",
        "custom_is_distribution_center",
        "custom_is_transit",
    ):
        if meta.has_field(optional):
            fields.append(optional)

    row = frappe.db.get_value(
        "Warehouse",
        warehouse_name,
        fields,
        as_dict=True,
    )
    if not row:
        frappe.throw(_("Warehouse {0} does not exist.").format(warehouse_name))

    return WarehouseInfo(
        name=row.name,
        company=row.company,
        disabled=row.disabled or 0,
        warehouse_type=row.warehouse_type,
        default_in_transit_warehouse=row.default_in_transit_warehouse,
        custom_is_store=row.get("custom_is_store") or 0,
        custom_is_distribution_center=row.get("custom_is_distribution_center") or 0,
        custom_is_transit=row.get("custom_is_transit") or 0,
    )


def get_physical_for_transit(transit_warehouse):
    """Resolve the one physical warehouse linked to a Transit warehouse."""
    rows = frappe.get_all(
        "Warehouse",
        filters={
            "default_in_transit_warehouse": transit_warehouse,
        },
        fields=["name", "company", "disabled", "warehouse_type"],
        limit_page_length=0,
    )

    if not rows:
        frappe.throw(
            _(
                "Transit warehouse {0} is not configured as the Default "
                "In-Transit Warehouse of any physical warehouse."
            ).format(transit_warehouse)
        )

    if len(rows) > 1:
        frappe.throw(
            _(
                "Transit warehouse {0} is linked to more than one physical "
                "warehouse. The mapping must be one-to-one."
            ).format(transit_warehouse)
        )

    return rows[0].name


def expected_transit_name(physical_warehouse):
    return f"{TRANSIT_PREFIX}{physical_warehouse}"


def validate_physical_warehouse(warehouse_name, *, require_active=True):
    info = get_warehouse_info(warehouse_name)

    if require_active and not info.is_active:
        frappe.throw(_("Warehouse {0} is disabled.").format(warehouse_name))

    if info.is_transit:
        frappe.throw(
            _("Warehouse {0} must be a physical warehouse, not Transit.").format(
                warehouse_name
            )
        )

    return info


def validate_transit_warehouse(
    warehouse_name,
    *,
    require_active=True,
    require_mapping=True,
    require_exact_name=True,
):
    info = get_warehouse_info(warehouse_name)

    if require_active and not info.is_active:
        frappe.throw(_("Transit warehouse {0} is disabled.").format(warehouse_name))

    if not info.is_transit:
        frappe.throw(
            _("Warehouse {0} must have Warehouse Type = Transit.").format(
                warehouse_name
            )
        )

    physical_name = None
    if require_mapping:
        physical_name = get_physical_for_transit(warehouse_name)
        physical = validate_physical_warehouse(physical_name, require_active=require_active)

        if physical.company != info.company:
            frappe.throw(
                _(
                    "Transit warehouse {0} and physical warehouse {1} must "
                    "belong to the same company."
                ).format(warehouse_name, physical_name)
            )

        if physical.default_in_transit_warehouse != warehouse_name:
            frappe.throw(
                _(
                    "Invalid Physical ↔ Transit mapping between {0} and {1}."
                ).format(physical_name, warehouse_name)
            )

        if require_exact_name and warehouse_name != expected_transit_name(physical_name):
            frappe.throw(
                _(
                    "Transit warehouse {0} must be named exactly {1}."
                ).format(
                    warehouse_name,
                    expected_transit_name(physical_name),
                )
            )

    return info, physical_name


def validate_physical_transit_pair(physical_warehouse, transit_warehouse):
    physical = validate_physical_warehouse(physical_warehouse)
    transit, linked_physical = validate_transit_warehouse(transit_warehouse)

    if physical.company != transit.company:
        frappe.throw(_("Source and target warehouses must belong to the same company."))

    if linked_physical == physical_warehouse:
        frappe.throw(
            _(
                "Send Stock cannot target the selected source warehouse's "
                "own Transit warehouse."
            )
        )

    if not physical.default_in_transit_warehouse:
        frappe.throw(
            _(
                "Physical warehouse {0} has no Default In-Transit Warehouse configured."
            ).format(physical_warehouse)
        )

    # The source's own mapping must itself be operationally valid, even though
    # Send Stock is targeting a different store's Transit warehouse.
    validate_transit_warehouse(physical.default_in_transit_warehouse)

    return physical, transit, linked_physical
