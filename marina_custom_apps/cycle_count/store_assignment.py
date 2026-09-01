import json

import frappe
from frappe import _


WAREHOUSE_USER_DOCTYPE = "Warehouse Users Allowed"


def eligible_store_warehouses(company):
    settings = frappe.get_single("DC Dispatch Settings")
    store_field = settings.warehouse_is_store_field

    if not frappe.get_meta("Warehouse").get_field(store_field):
        frappe.throw(
            _("Configured Warehouse store field {0} does not exist.").format(store_field)
        )

    return frappe.get_all(
        "Warehouse",
        filters={
            "company": company,
            "disabled": 0,
            "is_group": 0,
            store_field: 1,
        },
        pluck="name",
        order_by="name asc",
        limit_page_length=0,
    )


def _enabled_mapped_users(warehouses):
    # Return {warehouse: [enabled mapped users]} from Warehouse Users Allowed.
    warehouses = list(dict.fromkeys(warehouses or []))
    result = {warehouse: [] for warehouse in warehouses}

    if not warehouses:
        return result

    mappings = frappe.get_all(
        WAREHOUSE_USER_DOCTYPE,
        filters={
            "warehouse": ["in", warehouses],
            "user": ["is", "set"],
        },
        fields=["warehouse", "user"],
        limit_page_length=0,
    )

    mapped_users = sorted({row.user for row in mappings if row.user})
    if not mapped_users:
        return result

    enabled_users = set(
        frappe.get_all(
            "User",
            filters={
                "enabled": 1,
                "name": ["in", mapped_users],
            },
            pluck="name",
            limit_page_length=0,
        )
    )

    grouped = {warehouse: set() for warehouse in warehouses}
    for row in mappings:
        if row.warehouse in grouped and row.user in enabled_users:
            grouped[row.warehouse].add(row.user)

    return {
        warehouse: sorted(grouped.get(warehouse) or [])
        for warehouse in warehouses
    }


def warehouse_allowed_users(warehouse):
    return _enabled_mapped_users([warehouse]).get(warehouse, [])


def assignment_payload(company):
    warehouses = eligible_store_warehouses(company)
    mapped = _enabled_mapped_users(warehouses)

    out = []
    for warehouse in warehouses:
        users = mapped.get(warehouse, [])
        out.append(
            {
                "warehouse": warehouse,
                "users": users,
                "auto_user": users[0] if len(users) == 1 else None,
                "needs_selection": len(users) > 1,
                "missing_user": len(users) == 0,
            }
        )
    return out


def validate_assignment(warehouse, user):
    if not user:
        frappe.throw(_("Assigned Store User is required for {0}.").format(warehouse))

    exists = frappe.db.exists(
        WAREHOUSE_USER_DOCTYPE,
        {
            "warehouse": warehouse,
            "user": user,
        },
    )
    enabled = frappe.db.get_value("User", user, "enabled")

    if not exists or not enabled:
        frappe.throw(
            _("User {0} is not an enabled user in Warehouse Users Allowed for {1}.").format(
                user, warehouse
            )
        )


def parse_assignments(value):
    return json.loads(value or "{}") if isinstance(value, str) else (value or {})


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def allowed_user_query(doctype, txt, searchfield, start, page_len, filters):
    # Return only enabled users mapped to the selected warehouse.
    warehouse = (filters or {}).get("warehouse")
    if not warehouse:
        return []

    txt = (txt or "").strip()

    return frappe.db.sql(
        """
        select distinct
            u.name,
            u.full_name
        from `tabWarehouse Users Allowed` wua
        inner join `tabUser` u
            on u.name = wua.user
        where
            wua.warehouse = %(warehouse)s
            and u.enabled = 1
            and (
                u.name like %(txt)s
                or u.full_name like %(txt)s
            )
        order by
            u.full_name asc,
            u.name asc
        limit %(start)s, %(page_len)s
        """,
        {
            "warehouse": warehouse,
            "txt": f"%{txt}%",
            "start": int(start or 0),
            "page_len": int(page_len or 20),
        },
    )
