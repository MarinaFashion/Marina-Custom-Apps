from __future__ import annotations

import json
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr, getdate, now_datetime

from marina_custom_apps.pos_reconciliation.finance_review import (
    review_filtered_bank_only, review_selected_records, reset_selected_records,
)
from marina_custom_apps.pos_reconciliation.reconciliation_engine import execute_run
from marina_custom_apps.pos_reconciliation.review_service import (
    get_result_filter_options, get_results_page, get_source_page,
)


class POSReconciliationRun(Document):
    def validate(self):
        self.validate_date_range()
        self.validate_closed_run_immutability()

    def validate_closed_run_immutability(self):
        if self.is_new():
            return

        stored = frappe.db.get_value(
            self.doctype,
            self.name,
            ["status", "from_date", "to_date", "pos_profile", "card_type"],
            as_dict=True,
        )
        if not stored or stored.status != "Closed":
            return

        changed = []
        for fieldname in ("from_date", "to_date", "pos_profile", "card_type"):
            if cstr(self.get(fieldname) or "") != cstr(stored.get(fieldname) or ""):
                changed.append(fieldname)

        if changed:
            frappe.throw(
                _(
                    "Closed reconciliation runs are immutable. Reopen the run before changing: {0}."
                ).format(", ".join(changed))
            )

    def validate_date_range(self):
        if not self.from_date or not self.to_date:
            frappe.throw(_("From Date and To Date are required."))
        if getdate(self.from_date) > getdate(self.to_date):
            frappe.throw(_("From Date cannot be after To Date."))


def _writable_run(run_name):
    if not run_name:
        frappe.throw(_("Reconciliation Run is required."))
    run = frappe.get_doc("POS Reconciliation Run", run_name)
    run.check_permission("write")
    return run


def _ensure_open(run_name):
    run = frappe.get_doc("POS Reconciliation Run", run_name)
    if run.status != "Open":
        frappe.throw(_("This action is available only while the reconciliation run is Open."))
    return run


def _record_names(value):
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except ValueError:
            return [value]
    return list(value or [])


def _ensure_records_open(record_names):
    names = _record_names(record_names)
    if not names:
        return
    rows = frappe.get_all(
        "POS Reconciliation Record",
        filters={"name": ["in", names]},
        fields=["run"],
        group_by="run",
        limit_page_length=0,
    )
    for row in rows:
        if row.run:
            _ensure_open(row.run)


@frappe.whitelist()
def run_reconciliation(run_name):
    run = _writable_run(run_name)
    if run.status == "Closed":
        frappe.throw(_("Closed reconciliation runs must be reopened before re-running."))
    if cstr(run.execution_status).strip() == "Running":
        frappe.throw(_("This reconciliation run is already running."))

    frappe.db.set_value("POS Reconciliation Run", run.name, "execution_status", "Running", update_modified=True)

    try:
        result = execute_run(run_name)

        from marina_custom_apps.pos_reconciliation.accounting_service import sync_run_accounting_status
        sync_run_accounting_status(run_name)

        frappe.db.set_value(
            "POS Reconciliation Run",
            run.name,
            {"status": "Open", "execution_status": "Idle"},
            update_modified=True,
        )
        result["status"] = "Open"
        return result
    finally:
        # Do not leave a monthly period stuck in Running if reconciliation,
        # accounting synchronization, or a later hook raises an exception.
        frappe.db.set_value(
            "POS Reconciliation Run",
            run.name,
            "execution_status",
            "Idle",
            update_modified=False,
        )


@frappe.whitelist()
def close_reconciliation(run_name, note=None):
    run = _writable_run(run_name)
    if run.status != "Open":
        frappe.throw(_("Only an Open reconciliation run can be closed."))
    if not run.last_reconciled_on:
        frappe.throw(_("Run reconciliation at least once before closing this period."))
    if cstr(run.execution_status).strip() == "Running":
        frappe.throw(_("Wait for the current reconciliation execution to finish."))

    note = cstr(note).strip()
    now = now_datetime()
    values = {"status":"Closed","closed_by":frappe.session.user,"closed_on":now,"closing_note":note or None}
    frappe.db.set_value("POS Reconciliation Run", run.name, values, update_modified=True)
    run.add_comment("Info", _("Reconciliation closed by {0}.{1}").format(
        frappe.session.user, f" Closing note: {note}" if note else ""
    ))
    return values


@frappe.whitelist()
def reopen_reconciliation(run_name, reason):
    if not {"Accounts Manager","System Manager"}.intersection(set(frappe.get_roles())):
        frappe.throw(_("Only Accounts Manager or System Manager can reopen a closed reconciliation."), frappe.PermissionError)
    run = _writable_run(run_name)
    if run.status != "Closed":
        frappe.throw(_("Only a Closed reconciliation run can be reopened."))
    reason = cstr(reason).strip()
    if not reason:
        frappe.throw(_("Reopen Reason is required."))
    now = now_datetime()
    values = {"status":"Open","reopened_by":frappe.session.user,"reopened_on":now,"reopen_reason":reason,"execution_status":"Idle"}
    frappe.db.set_value("POS Reconciliation Run", run.name, values, update_modified=True)
    run.add_comment("Info", _("Reconciliation reopened by {0}. Reason: {1}").format(frappe.session.user, reason))
    return values


@frappe.whitelist()
def get_source_review_page(run_name, source, start=0, page_length=25, search=None):
    return get_source_page(run_name, source, start=start, page_length=page_length, search=search)


@frappe.whitelist()
def get_results_review_page(
    run_name,status="All",start=0,page_length=25,search=None,from_date=None,to_date=None,
    settlement_number=None,settlement_date=None,pos_profile=None,terminal_id=None,card_type=None,
    finance_review_status=None,accounting_status=None,ledger_posting_status=None,before_integration=None,
):
    return get_results_page(
        run_name,status=status,start=start,page_length=page_length,search=search,from_date=from_date,to_date=to_date,
        settlement_number=settlement_number,settlement_date=settlement_date,pos_profile=pos_profile,
        terminal_id=terminal_id,card_type=card_type,finance_review_status=finance_review_status,
        accounting_status=accounting_status,ledger_posting_status=ledger_posting_status,before_integration=before_integration,
    )


@frappe.whitelist()
def get_review_filter_options(
    run_name,status="All",from_date=None,to_date=None,settlement_number=None,settlement_date=None,
    pos_profile=None,terminal_id=None,card_type=None,finance_review_status=None,accounting_status=None,
    ledger_posting_status=None,before_integration=None,
):
    return get_result_filter_options(
        run_name,status=status,from_date=from_date,to_date=to_date,settlement_number=settlement_number,
        settlement_date=settlement_date,pos_profile=pos_profile,terminal_id=terminal_id,card_type=card_type,
        finance_review_status=finance_review_status,accounting_status=accounting_status,
        ledger_posting_status=ledger_posting_status,before_integration=before_integration,
    )


@frappe.whitelist()
def finance_review_selected(record_names, decision, note=None):
    _ensure_records_open(record_names)
    return review_selected_records(record_names, decision, note)


@frappe.whitelist()
def finance_review_reset(record_names):
    _ensure_records_open(record_names)
    return reset_selected_records(record_names)


@frappe.whitelist()
def finance_review_filtered(
    run_name,settlement_number,decision,note=None,from_date=None,to_date=None,settlement_date=None,
    pos_profile=None,terminal_id=None,card_type=None,finance_review_status=None,accounting_status=None,
    ledger_posting_status=None,before_integration=None,search=None,
):
    _ensure_open(run_name)
    return review_filtered_bank_only(
        run_name,settlement_number,decision,note=note,from_date=from_date,to_date=to_date,
        settlement_date=settlement_date,pos_profile=pos_profile,terminal_id=terminal_id,card_type=card_type,
        finance_review_status=finance_review_status,accounting_status=accounting_status,
        ledger_posting_status=ledger_posting_status,before_integration=before_integration,search=search,
    )


@frappe.whitelist()
def get_accounting_options(run_name):
    _ensure_open(run_name)
    from marina_custom_apps.pos_reconciliation.accounting_service import get_accounting_filter_options
    return get_accounting_filter_options(run_name)


@frappe.whitelist()
def get_accounting_preview_for_run(run_name, posting_date, pos_profile=None):
    _ensure_open(run_name)
    from marina_custom_apps.pos_reconciliation.accounting_service import get_accounting_preview
    return get_accounting_preview(run_name, posting_date, pos_profile=pos_profile)


@frappe.whitelist()
def create_accounting_entries(run_name, posting_date, pos_profile=None):
    _ensure_open(run_name)
    from marina_custom_apps.pos_reconciliation.accounting_service import create_accounting_postings
    return create_accounting_postings(run_name, posting_date, pos_profile=pos_profile)