from __future__ import annotations

import json
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr, getdate, now_datetime

from marina_custom_apps.pos_reconciliation.reconciliation_engine import execute_run
from marina_custom_apps.pos_reconciliation.review_service import (
    get_result_filter_options, get_results_page, get_source_page,
)


class POSReconciliationRun(Document):
    def validate(self):
        if self.from_date and self.to_date and getdate(self.from_date) > getdate(self.to_date):
            frappe.throw(_("From Date cannot be after To Date."))
        # A user's stale Single form Save must never replace the worker's
        # execution lock, accounting summary or system-managed result fields.
        for fieldname in (
            "status", "execution_status", "execution_job_id",
            "execution_queued_on", "execution_started_on", "execution_completed_on",
            "execution_error", "last_reconciled_on",
            "bank_transaction_count", "alhamrani_transaction_count",
            "statement_transaction_count", "statement_reconciled_count",
            "statement_unreconciled_count", "statement_pos_line_count",
            "statement_settlement_count", "statement_fully_reconciled_settlements",
            "statement_missing_identity_count", "matching_count",
            "matching_not_settled_count", "discrepancy_count", "bank_only_count",
            "bank_only_settled_count", "bank_only_not_settled_count",
            "alhamrani_only_count", "manually_cleared_count", "pending_count",
        ):
            self.set(fieldname, frappe.db.get_single_value(self.doctype, fieldname))


def _writable_run(run_name=None):
    if run_name and cstr(run_name) != "POS Reconciliation Run":
        frappe.throw(_("Only the Single POS Reconciliation Run control is supported."))
    run = frappe.get_single("POS Reconciliation Run")
    run.check_permission("write")
    return run


def _ensure_open(run_name=None):
    run = frappe.get_single("POS Reconciliation Run")
    run.check_permission("read")
    if run.status != "Open":
        frappe.throw(_("Run reconciliation once before performing this action."))
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
    _ensure_open()
    from marina_custom_apps.pos_reconciliation.period_control import assert_records_open
    assert_records_open(_record_names(record_names))


def _set_control_fields(values):
    for key, value in values.items():
        frappe.db.set_single_value("POS Reconciliation Run", key, value)


def _validate_execution_input(data):
    if not data["from_date"] or not data["to_date"]:
        frappe.throw(_("From Date and To Date are required."))
    data["from_date"], data["to_date"] = getdate(data["from_date"]), getdate(data["to_date"])
    if data["from_date"] > data["to_date"]:
        frappe.throw(_("From Date cannot be after To Date."))
    for fieldname, doctype in (("pos_profile", "POS Profile"), ("bank_account", "Bank Account")):
        if data[fieldname] and not frappe.db.exists(doctype, data[fieldname]):
            frappe.throw(_("Invalid {0}: {1}.").format(fieldname, data[fieldname]))
    from marina_custom_apps.pos_reconciliation.period_control import assert_scope_open
    assert_scope_open(data["from_date"], data["to_date"])


@frappe.whitelist()
def run_reconciliation(
    run_name=None, from_date=None, to_date=None, pos_profile=None,
    card_type=None, bank_account=None,
):
    """Queue a snapshot of form inputs, not a mutable global Run."""
    run = _writable_run(run_name)
    scope = {
        fieldname: cstr(value if value is not None else run.get(fieldname) or "").strip()
        for fieldname, value in (
            ("from_date", from_date), ("to_date", to_date),
            ("pos_profile", pos_profile), ("card_type", card_type),
            ("bank_account", bank_account),
        )
    }
    _validate_execution_input(scope)
    # Serialise concurrent requests even if two Finance users click at once.
    frappe.db.sql(
        "SELECT name FROM `tabDocType` WHERE name = 'POS Reconciliation Run' FOR UPDATE"
    )
    status = cstr(frappe.db.get_single_value("POS Reconciliation Run", "execution_status"))
    if status in {"Queued", "Running"}:
        frappe.throw(_("A POS reconciliation job is already queued or running."))

    now = now_datetime()
    execution = frappe.new_doc("POS Reconciliation Execution")
    execution.update(scope)
    execution.run_status = "Queued"
    execution.initiated_by = frappe.session.user
    execution.initiated_on = now
    execution.queued_on = now
    execution.flags.ignore_permissions = True
    execution.insert()
    job_id = f"pos-reconciliation-single::{execution.name}"
    _set_control_fields({
        **scope, "execution_status": "Queued", "execution_job_id": job_id,
        "execution_queued_on": now, "execution_started_on": None,
        "execution_completed_on": None, "execution_error": None,
    })
    frappe.enqueue(
        "marina_custom_apps.pos_reconciliation.doctype.pos_reconciliation_run.pos_reconciliation_run.execute_reconciliation_job",
        queue="long", timeout=3600, job_id=job_id, enqueue_after_commit=True,
        execution_name=execution.name,
    )
    return {"execution": execution.name, "execution_status": "Queued", "job_id": job_id}


def execute_reconciliation_job(execution_name):
    """Worker uses immutable execution inputs even if someone opens/saves the Single form."""
    execution = frappe.get_doc("POS Reconciliation Execution", execution_name)
    if execution.run_status != "Queued":
        frappe.throw(_("Execution is not queued."))
    started = now_datetime()
    frappe.db.set_value(
        "POS Reconciliation Execution", execution.name,
        {"run_status": "Running", "started_on": started},
        update_modified=False,
    )
    _set_control_fields({"execution_status": "Running", "execution_started_on": started})
    frappe.db.commit()

    try:
        run = frappe.get_single("POS Reconciliation Run")
        for fieldname in ("from_date", "to_date", "pos_profile", "card_type", "bank_account"):
            run.set(fieldname, execution.get(fieldname))
        # execute_run modifies only the source scope; account postings stay separate.
        result = execute_run(run, execution_name=execution.name)

        completed = now_datetime()
        frappe.db.set_value(
            "POS Reconciliation Execution", execution.name,
            {
                "run_status": "Completed", "completed_on": completed,
                **{
                    field: result.get(field, 0)
                    for field in (
                        "bank_transaction_count", "alhamrani_transaction_count",
                        "matching_count", "pending_count",
                        "statement_transaction_count", "statement_reconciled_count",
                    )
                },
            },
            update_modified=False,
        )
        _set_control_fields({
            "status": "Open", "execution_status": "Completed",
            "execution_completed_on": completed, "execution_error": None,
        })
        frappe.db.commit()
        return {"execution": execution.name, "status": "Completed", **(result or {})}
    except Exception:
        frappe.db.rollback()
        details = cstr(frappe.get_traceback())[-12000:]
        frappe.db.set_value(
            "POS Reconciliation Execution", execution.name,
            {"run_status": "Failed", "completed_on": now_datetime(), "error": details},
            update_modified=False,
        )
        _set_control_fields({
            "execution_status": "Failed",
            "execution_completed_on": now_datetime(), "execution_error": details,
        })
        frappe.db.commit()
        raise


@frappe.whitelist()
def close_reconciliation(run_name=None, note=None, from_date=None, to_date=None):
    run = _writable_run(run_name)
    from marina_custom_apps.pos_reconciliation.period_control import close_period
    return close_period(from_date or run.from_date, to_date or run.to_date, note)


@frappe.whitelist()
def reopen_reconciliation(run_name=None, reason=None, period_lock=None):
    _writable_run(run_name)
    if not period_lock:
        frappe.throw(_("Select the period lock from the Period Locks list to reopen it."))
    from marina_custom_apps.pos_reconciliation.period_control import reopen_period
    return reopen_period(period_lock, reason)


@frappe.whitelist()
def get_source_review_page(run_name, source, start=0, page_length=25, search=None):
    return get_source_page(run_name, source, start=start, page_length=page_length, search=search)


@frappe.whitelist()
def get_results_review_page(
    run_name,status="All",start=0,page_length=25,search=None,from_date=None,to_date=None,
    settlement_number=None,settlement_date=None,pos_profile=None,terminal_id=None,card_type=None,
    finance_review_status=None,bank_statement_status=None,accounting_status=None,ledger_posting_status=None,before_integration=None,
):
    return get_results_page(
        run_name,status=status,start=start,page_length=page_length,search=search,from_date=from_date,to_date=to_date,
        settlement_number=settlement_number,settlement_date=settlement_date,pos_profile=pos_profile,
        terminal_id=terminal_id,card_type=card_type,finance_review_status=finance_review_status,
        bank_statement_status=bank_statement_status,accounting_status=accounting_status,
        ledger_posting_status=ledger_posting_status,before_integration=before_integration,
    )


@frappe.whitelist()
def get_review_filter_options(
    run_name,status="All",from_date=None,to_date=None,settlement_number=None,settlement_date=None,
    pos_profile=None,terminal_id=None,card_type=None,finance_review_status=None,bank_statement_status=None,accounting_status=None,
    ledger_posting_status=None,before_integration=None,
):
    return get_result_filter_options(
        run_name,status=status,from_date=from_date,to_date=to_date,settlement_number=settlement_number,
        settlement_date=settlement_date,pos_profile=pos_profile,terminal_id=terminal_id,card_type=card_type,
        finance_review_status=finance_review_status,bank_statement_status=bank_statement_status,accounting_status=accounting_status,
        ledger_posting_status=ledger_posting_status,before_integration=before_integration,
    )


@frappe.whitelist()
def finance_review_selected(record_names, decision, note=None):
    frappe.throw(_("Manual Finance clearance is retired. Settled reconciliation statuses are evaluated automatically."))


@frappe.whitelist()
def finance_review_reset(record_names):
    frappe.throw(_("Manual Finance clearance is retired. Settled reconciliation statuses are evaluated automatically."))


@frappe.whitelist()
def finance_review_filtered(
    run_name,settlement_number,decision,note=None,from_date=None,to_date=None,settlement_date=None,
    pos_profile=None,terminal_id=None,card_type=None,finance_review_status=None,bank_statement_status=None,accounting_status=None,
    ledger_posting_status=None,before_integration=None,search=None,
):
    frappe.throw(_("Manual Finance clearance is retired. Settled reconciliation statuses are evaluated automatically."))


@frappe.whitelist()
def get_accounting_options(run_name):
    _ensure_open(run_name)
    from marina_custom_apps.pos_reconciliation.accounting_service import get_accounting_filter_options
    return get_accounting_filter_options(run_name)


@frappe.whitelist()
def get_accounting_preview_for_run(
    run_name, posting_date, pos_profile=None, from_date=None, to_date=None
):
    _ensure_open(run_name)
    from marina_custom_apps.pos_reconciliation.accounting_service import get_accounting_preview
    return get_accounting_preview(
        run_name,
        posting_date,
        pos_profile=pos_profile,
        from_date=from_date,
        to_date=to_date,
    )


@frappe.whitelist()
def create_accounting_entries(
    run_name, posting_date, pos_profile=None, from_date=None, to_date=None
):
    _ensure_open(run_name)
    from marina_custom_apps.pos_reconciliation.accounting_service import create_accounting_postings
    return create_accounting_postings(
        run_name,
        posting_date,
        pos_profile=pos_profile,
        from_date=from_date,
        to_date=to_date,
    )