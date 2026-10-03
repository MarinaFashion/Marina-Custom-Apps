import frappe
from frappe import _


def execute(filters=None):
    filters = frappe._dict(filters or {})
    if not filters.run:
        frappe.throw(_("Reconciliation Run is required."))
    return get_columns(), get_data(filters)


def get_columns():
    return [
        {"label": _("Date"), "fieldname": "transaction_date", "fieldtype": "Date", "width": 100},
        {"label": _("POS Profile"), "fieldname": "pos_profile", "fieldtype": "Link", "options": "POS Profile", "width": 170},
        {"label": _("Terminal"), "fieldname": "terminal_id", "fieldtype": "Data", "width": 150},
        {"label": _("Settlement No."), "fieldname": "settlement_number", "fieldtype": "Data", "width": 115},
        {"label": _("Settlement Date"), "fieldname": "settlement_date", "fieldtype": "Date", "width": 105},
        {"label": _("Card Type"), "fieldname": "card_type", "fieldtype": "Data", "width": 100},
        {"label": _("Match Status"), "fieldname": "match_status", "fieldtype": "Data", "width": 115},
        {"label": _("Resolution"), "fieldname": "resolution_status", "fieldtype": "Data", "width": 120},
        {"label": _("Finance Review"), "fieldname": "finance_review_status", "fieldtype": "Data", "width": 135},
        {"label": _("Reviewed By"), "fieldname": "finance_reviewed_by", "fieldtype": "Link", "options": "User", "width": 140},
        {"label": _("Before Integration"), "fieldname": "before_integration", "fieldtype": "Check", "width": 105},
        {"label": _("Bank Transaction"), "fieldname": "bank_transaction", "fieldtype": "Link", "options": "Bank POS Transaction", "width": 145},
        {"label": _("Alhamrani Transaction"), "fieldname": "alhamrani_transaction", "fieldtype": "Data", "width": 155},
        {"label": _("Bank Amount"), "fieldname": "bank_amount", "fieldtype": "Currency", "width": 110},
        {"label": _("Commission"), "fieldname": "bank_commission_amount", "fieldtype": "Currency", "width": 100},
        {"label": _("VAT on Commission"), "fieldname": "bank_commission_vat_amount", "fieldtype": "Currency", "width": 115},
        {"label": _("Alhamrani Amount"), "fieldname": "alhamrani_amount", "fieldtype": "Currency", "width": 120},
        {"label": _("Difference"), "fieldname": "amount_difference", "fieldtype": "Currency", "width": 105},
        {"label": _("PAN Validation"), "fieldname": "pan_validation_method", "fieldtype": "Data", "width": 110},
        {"label": _("Discrepancy Fields"), "fieldname": "discrepancy_fields", "fieldtype": "Data", "width": 190},
        {"label": _("Finance Note"), "fieldname": "finance_review_note", "fieldtype": "Data", "width": 190},
    ]


def get_data(filters):
    db_filters = {"run": filters.run}
    for fieldname in (
        "match_status",
        "resolution_status",
        "finance_review_status",
        "pos_profile",
        "card_type",
        "settlement_number",
        "settlement_date",
        "terminal_id",
    ):
        value = filters.get(fieldname)
        if value:
            db_filters[fieldname] = value
    if filters.get("from_date") and filters.get("to_date"):
        db_filters["transaction_date"] = ["between", [filters.from_date, filters.to_date]]
    elif filters.get("from_date"):
        db_filters["transaction_date"] = [">=", filters.from_date]
    elif filters.get("to_date"):
        db_filters["transaction_date"] = ["<=", filters.to_date]
    if filters.get("before_integration"):
        db_filters["before_integration"] = 1

    return frappe.get_list(
        "POS Reconciliation Record",
        filters=db_filters,
        fields=[
            "transaction_date",
            "pos_profile",
            "terminal_id",
            "settlement_number",
            "settlement_date",
            "card_type",
            "match_status",
            "resolution_status",
            "finance_review_status",
            "finance_reviewed_by",
            "before_integration",
            "bank_transaction",
            "alhamrani_transaction",
            "bank_amount",
            "bank_commission_amount",
            "bank_commission_vat_amount",
            "alhamrani_amount",
            "amount_difference",
            "pan_validation_method",
            "discrepancy_fields",
            "finance_review_note",
        ],
        order_by="transaction_date desc, terminal_id asc",
        limit_page_length=0,
    )
