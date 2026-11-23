"""ERPNext Script Report: candidate accruals only, read-only."""
import frappe
from frappe import _

from marina_custom_apps.marina_leave_management.monthly_preview import get_candidates


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = [
        {"label": _("Employee"), "fieldname": "employee",
         "fieldtype": "Link", "options": "Employee", "width": 145},
        {"label": _("Employee Name"), "fieldname": "employee_name",
         "fieldtype": "Data", "width": 175},
        {"label": _("Contract"), "fieldname": "entitlement",
         "fieldtype": "Data", "width": 120},
        {"label": _("Period"), "fieldname": "period",
         "fieldtype": "Data", "width": 95},
        {"label": _("Credit Date"), "fieldname": "credit_date",
         "fieldtype": "Date", "width": 110},
        {"label": _("Excluded Days"), "fieldname": "excluded_days",
         "fieldtype": "Float", "precision": 6, "width": 135},
        {"label": _("Provisional Monthly Credit"),
         "fieldname": "candidate_credit", "fieldtype": "Float",
         "precision": 6, "width": 190},
        {"label": _("Exempt"), "fieldname": "exempt",
         "fieldtype": "Check", "width": 80},
        {"label": _("Status"), "fieldname": "status",
         "fieldtype": "Data", "width": 160},
        {"label": _("Review Notes"), "fieldname": "notes",
         "fieldtype": "Small Text", "width": 420},
    ]
    return columns, get_candidates(
        credit_date=filters.get("credit_date"),
        employee=filters.get("employee"),
        entitlement=filters.get("entitlement"),
        include_exempt=bool(filters.get("include_exempt")),
        company=filters.get("company"),
    )
