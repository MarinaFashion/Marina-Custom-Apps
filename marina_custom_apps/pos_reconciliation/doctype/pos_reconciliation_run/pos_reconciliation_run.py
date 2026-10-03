from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from marina_custom_apps.pos_reconciliation.finance_review import (
    review_filtered_bank_only,
    review_selected_records,
    reset_selected_records,
)
from marina_custom_apps.pos_reconciliation.reconciliation_engine import execute_run
from marina_custom_apps.pos_reconciliation.review_service import (
    get_result_filter_options,
    get_results_page,
    get_source_page,
)


class POSReconciliationRun(Document):
    def validate(self):
        self.validate_date_range()

    def validate_date_range(self):
        if not self.from_date or not self.to_date:
            frappe.throw(_("From Date and To Date are required."))
        if getdate(self.from_date) > getdate(self.to_date):
            frappe.throw(_("From Date cannot be after To Date."))


@frappe.whitelist()
def run_reconciliation(run_name):
    return execute_run(run_name)


@frappe.whitelist()
def get_source_review_page(run_name, source, start=0, page_length=25, search=None):
    return get_source_page(
        run_name,
        source,
        start=start,
        page_length=page_length,
        search=search,
    )


@frappe.whitelist()
def get_results_review_page(
    run_name,
    status="All",
    start=0,
    page_length=25,
    search=None,
    from_date=None,
    to_date=None,
    settlement_number=None,
    settlement_date=None,
    pos_profile=None,
    terminal_id=None,
    card_type=None,
    finance_review_status=None,
    before_integration=None,
):
    return get_results_page(
        run_name,
        status=status,
        start=start,
        page_length=page_length,
        search=search,
        from_date=from_date,
        to_date=to_date,
        settlement_number=settlement_number,
        settlement_date=settlement_date,
        pos_profile=pos_profile,
        terminal_id=terminal_id,
        card_type=card_type,
        finance_review_status=finance_review_status,
        before_integration=before_integration,
    )


@frappe.whitelist()
def get_review_filter_options(run_name, status="Bank Pending"):
    return get_result_filter_options(run_name, status=status)


@frappe.whitelist()
def finance_review_selected(record_names, decision, note=None):
    return review_selected_records(record_names, decision, note)


@frappe.whitelist()
def finance_review_reset(record_names):
    return reset_selected_records(record_names)


@frappe.whitelist()
def finance_review_filtered(
    run_name,
    settlement_number,
    decision,
    note=None,
    from_date=None,
    to_date=None,
    settlement_date=None,
    pos_profile=None,
    terminal_id=None,
    card_type=None,
    finance_review_status=None,
    before_integration=None,
    search=None,
):
    return review_filtered_bank_only(
        run_name,
        settlement_number,
        decision,
        note=note,
        from_date=from_date,
        to_date=to_date,
        settlement_date=settlement_date,
        pos_profile=pos_profile,
        terminal_id=terminal_id,
        card_type=card_type,
        finance_review_status=finance_review_status,
        before_integration=before_integration,
        search=search,
    )
