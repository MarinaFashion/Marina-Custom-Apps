import frappe
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
from frappe.utils import cint, flt

from marina_custom_apps.stock_transfer_audit.control_service import (
    get_open_transit_rows,
    get_settings,
    get_variance_value_maps,
)


def _role_users(role):
    if not role:
        return []

    candidates = frappe.get_all(
        "Has Role",
        filters={"role": role, "parenttype": "User"},
        pluck="parent",
        limit_page_length=0,
    )
    if not candidates:
        return []

    return frappe.get_all(
        "User",
        filters={"name": ["in", candidates], "enabled": 1, "user_type": "System User"},
        pluck="name",
        limit_page_length=0,
    )


def _pending_audit_metrics(settings):
    records = frappe.get_all(
        "Stock Transfer Audit Record",
        filters={"docstatus": 1, "processing_status": "Pending"},
        fields=["name", "total_abs_variance_qty"],
        limit_page_length=0,
    )
    values, _ = get_variance_value_maps([r.name for r in records])

    large = 0
    for row in records:
        if (
            flt(row.total_abs_variance_qty) >= flt(settings.large_variance_qty_threshold)
            or flt(values.get(row.name)) >= flt(settings.large_variance_value_threshold)
        ):
            large += 1

    return len(records), large


def send_daily_stock_transfer_control_alerts():
    settings = get_settings()
    if not cint(settings.enable_daily_alerts):
        return

    users = _role_users(settings.alert_role or "Stock Manager")
    if not users:
        return

    open_rows = get_open_transit_rows()
    overdue = sum(1 for row in open_rows if row.aging_status in ("Overdue", "Critical"))
    critical = sum(1 for row in open_rows if row.aging_status == "Critical")
    pending, large = _pending_audit_metrics(settings)

    if not overdue and not pending:
        return

    subject = (
        f"Stock Transfer Control: {overdue} overdue transit, "
        f"{pending} pending audits"
    )
    description = (
        f"Open transit: {len(open_rows)}<br>"
        f"Overdue transit: {overdue}<br>"
        f"Critical transit: {critical}<br>"
        f"Pending audit records: {pending}<br>"
        f"Large variance records: {large}<br><br>"
        "Open the Stock Transfer Audit workspace for action."
    )

    enqueue_create_notification(
        users,
        {
            "type": "Stock Transfer Control",
            "subject": subject,
            "description": description,
            "from_user": "Administrator",
            "link": "/app/stock-transfer-audit",
        },
    )
