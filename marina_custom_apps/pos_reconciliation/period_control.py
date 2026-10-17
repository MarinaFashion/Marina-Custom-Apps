"""Financial-period locks independent from POS Reconciliation Run (Single)."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cstr, getdate, now_datetime

DOCTYPE = "POS Reconciliation Period Lock"


def _reject_during_execution():
    state = cstr(frappe.db.get_single_value("POS Reconciliation Run", "execution_status"))
    if state in {"Queued", "Running"}:
        frappe.throw(_("Wait for the active POS reconciliation execution to finish before changing Finance or accounting evidence."))


def assert_scope_open(from_date, to_date):
    if not from_date or not to_date:
        frappe.throw(_("From Date and To Date are required."))
    start, end = getdate(from_date), getdate(to_date)
    if start > end:
        frappe.throw(_("From Date must be on or before To Date."))
    locked = frappe.get_all(
        DOCTYPE,
        filters={"status": "Closed", "from_date": ["<=", end], "to_date": [">=", start]},
        fields=["name", "from_date", "to_date"],
        order_by="from_date",
        limit_page_length=1,
    )
    if locked:
        row = locked[0]
        frappe.throw(
            _("Selected dates overlap closed POS reconciliation period {0} ({1} to {2}). Reopen the period before changing its results.").format(
                row.name, row.from_date, row.to_date
            )
        )


def assert_dates_open(dates):
    days = {getdate(value) for value in dates if value}
    if not days:
        return
    start, end = min(days), max(days)
    locked = frappe.get_all(
        DOCTYPE,
        filters={"status": "Closed", "from_date": ["<=", end], "to_date": [">=", start]},
        fields=["name", "from_date", "to_date"],
        limit_page_length=0,
    )
    for row in locked:
        if any(getdate(row.from_date) <= day <= getdate(row.to_date) for day in days):
            frappe.throw(_("Finance period {0} is Closed. Reopen it before modifying reconciliation records.").format(row.name))


def assert_records_open(record_names):
    _reject_during_execution()
    names = list(dict.fromkeys(cstr(name).strip() for name in record_names or [] if cstr(name).strip()))
    for start in range(0, len(names), 500):
        chunk = names[start:start + 500]
        rows = frappe.get_all(
            "POS Reconciliation Record",
            filters={"name": ["in", chunk]},
            fields=["transaction_date"],
            limit_page_length=0,
        )
        assert_dates_open(row.transaction_date for row in rows)


def assert_bank_transactions_open(bank_names):
    _reject_during_execution()
    names = list(dict.fromkeys(cstr(name).strip() for name in bank_names or [] if cstr(name).strip()))
    for start in range(0, len(names), 500):
        rows = frappe.get_all(
            "Bank POS Transaction",
            filters={"name": ["in", names[start:start + 500]]},
            fields=["transaction_date"],
            limit_page_length=0,
        )
        assert_dates_open(row.transaction_date for row in rows)


def _manager_permission():
    if not {"Accounts Manager", "System Manager"}.intersection(set(frappe.get_roles())):
        frappe.throw(_("Only Accounts Manager or System Manager can close or reopen periods."), frappe.PermissionError)


def close_period(from_date, to_date, note=None):
    _manager_permission()
    assert_scope_open(from_date, to_date)
    run = frappe.get_single("POS Reconciliation Run")
    if cstr(run.execution_status) in {"Queued", "Running"}:
        frappe.throw(_("Wait for the active reconciliation execution to finish."))
    if not run.last_reconciled_on:
        frappe.throw(_("Run reconciliation before closing a financial period."))
    # The lock applies to all stores/cards; never close all on a partial run.
    completed = frappe.db.sql(
        """SELECT name FROM `tabPOS Reconciliation Execution`
           WHERE run_status = 'Completed'
             AND from_date <= %s AND to_date >= %s
             AND COALESCE(pos_profile, '') = ''
             AND COALESCE(card_type, '') = ''
           LIMIT 1""",
        (getdate(from_date), getdate(to_date)),
    )
    if not completed:
        frappe.throw(
            _("Closing a global period requires a completed reconciliation covering these dates without POS Profile or Card Type filters.")
        )
    doc = frappe.new_doc(DOCTYPE)
    doc.status = "Closed"
    doc.from_date, doc.to_date = getdate(from_date), getdate(to_date)
    doc.closed_by, doc.closed_on = frappe.session.user, now_datetime()
    doc.closing_note = cstr(note or "").strip()
    doc.flags.ignore_permissions = True
    doc.insert()
    return {"name": doc.name, "status": doc.status}


def reopen_period(name, reason):
    _manager_permission()
    reason = cstr(reason or "").strip()
    if not reason:
        frappe.throw(_("Reopen Reason is required."))
    doc = frappe.get_doc(DOCTYPE, name)
    if doc.status != "Closed":
        frappe.throw(_("This period is not Closed."))
    if cstr(frappe.get_single("POS Reconciliation Run").execution_status) in {"Queued", "Running"}:
        frappe.throw(_("Wait for active reconciliation execution to finish."))
    doc.status = "Reopened"
    doc.reopened_by, doc.reopened_on, doc.reopen_reason = frappe.session.user, now_datetime(), reason
    doc.flags.ignore_permissions = True
    doc.save()
    return {"name": doc.name, "status": doc.status}
