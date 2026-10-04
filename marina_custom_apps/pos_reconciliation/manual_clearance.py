from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from marina_custom_apps.pos_reconciliation.reconciliation_engine import (
    FINANCE_APPROVED,
    FINANCE_PENDING,
    refresh_run_summary,
)


def _as_list(value):
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except ValueError:
            return [value]
    return list(value or [])


def _check_permission():
    if not frappe.has_permission("POS Bank Manual Clearance", ptype="write"):
        frappe.throw(_("You are not permitted to manage POS manual clearances."), frappe.PermissionError)



def _ensure_bank_transactions_open(bank_transactions):
    bank_transactions = list(dict.fromkeys(_as_list(bank_transactions)))
    if not bank_transactions:
        return

    rows = frappe.get_all(
        "POS Reconciliation Record",
        filters={"bank_transaction": ["in", bank_transactions]},
        fields=["run"],
        group_by="run",
        limit_page_length=0,
    )
    for row in rows:
        if row.run and frappe.db.get_value("POS Reconciliation Run", row.run, "status") == "Closed":
            frappe.throw(
                _("Closed reconciliation runs must be reopened before manual clearance can be changed.")
            )

def _clearance_doc(bank_transaction):
    name = frappe.db.get_value(
        "POS Bank Manual Clearance",
        {"bank_transaction": bank_transaction},
        "name",
    )
    if name:
        return frappe.get_doc("POS Bank Manual Clearance", name)
    return frappe.new_doc("POS Bank Manual Clearance")


def mark_bank_transactions(bank_transactions, reason=None):
    """Backward-compatible manual clearance; now also records Finance approval."""
    _check_permission()
    bank_transactions = list(dict.fromkeys(_as_list(bank_transactions)))
    _ensure_bank_transactions_open(bank_transactions)
    if not bank_transactions:
        return {"updated": 0}

    reason = (reason or _("Finance checked and approved")).strip()
    now = now_datetime()
    affected_runs = set()
    updated = 0

    for bank_name in bank_transactions:
        if not frappe.db.exists("Bank POS Transaction", bank_name):
            continue

        doc = _clearance_doc(bank_name)
        doc.bank_transaction = bank_name
        doc.active = 1
        doc.reason = reason
        doc.finance_review_status = FINANCE_APPROVED
        doc.finance_review_note = reason
        doc.finance_reviewed_by = frappe.session.user
        doc.finance_reviewed_on = now
        doc.cleared_by = frappe.session.user
        doc.cleared_on = now
        doc.reopened_by = None
        doc.reopened_on = None
        doc.flags.ignore_permissions = True
        doc.save()
        updated += 1

        records = frappe.get_all(
            "POS Reconciliation Record",
            filters={"bank_transaction": bank_name, "match_status": "Bank Only"},
            fields=["name", "run"],
            limit_page_length=0,
        )
        for row in records:
            frappe.db.set_value(
                "POS Reconciliation Record",
                row.name,
                {
                    "resolution_status": "Manually Cleared",
                    "finance_review_status": FINANCE_APPROVED,
                    "finance_reviewed_by": frappe.session.user,
                    "finance_reviewed_on": now,
                    "finance_review_note": reason,
                    "manual_clearance_reason": reason,
                    "manual_cleared_by": frappe.session.user,
                    "manual_cleared_on": now,
                },
                update_modified=True,
            )
            affected_runs.add(row.run)

    for run_name in affected_runs:
        refresh_run_summary(run_name)

    from marina_custom_apps.pos_reconciliation.accounting_service import sync_accounting_status_for_bank_transactions

    sync_accounting_status_for_bank_transactions(bank_transactions)
    return {"updated": updated, "affected_runs": len(affected_runs)}


def reopen_bank_transactions(bank_transactions):
    _check_permission()
    bank_transactions = list(dict.fromkeys(_as_list(bank_transactions)))
    _ensure_bank_transactions_open(bank_transactions)
    now = now_datetime()
    affected_runs = set()
    updated = 0

    for bank_name in bank_transactions:
        name = frappe.db.get_value(
            "POS Bank Manual Clearance",
            {"bank_transaction": bank_name},
            "name",
        )
        if not name:
            continue

        doc = frappe.get_doc("POS Bank Manual Clearance", name)
        doc.active = 0
        doc.finance_review_status = FINANCE_PENDING
        doc.finance_review_note = None
        doc.finance_reviewed_by = None
        doc.finance_reviewed_on = None
        doc.reopened_by = frappe.session.user
        doc.reopened_on = now
        doc.flags.ignore_permissions = True
        doc.save()
        updated += 1

        records = frappe.get_all(
            "POS Reconciliation Record",
            filters={"bank_transaction": bank_name, "match_status": "Bank Only"},
            fields=["name", "run"],
            limit_page_length=0,
        )
        for row in records:
            frappe.db.set_value(
                "POS Reconciliation Record",
                row.name,
                {
                    "resolution_status": "Pending",
                    "finance_review_status": FINANCE_PENDING,
                    "finance_reviewed_by": None,
                    "finance_reviewed_on": None,
                    "finance_review_note": None,
                    "manual_clearance_reason": None,
                    "manual_cleared_by": None,
                    "manual_cleared_on": None,
                },
                update_modified=True,
            )
            affected_runs.add(row.run)

    for run_name in affected_runs:
        refresh_run_summary(run_name)

    from marina_custom_apps.pos_reconciliation.accounting_service import sync_accounting_status_for_bank_transactions

    sync_accounting_status_for_bank_transactions(bank_transactions)
    return {"updated": updated, "affected_runs": len(affected_runs)}


def _validate_single_settlement(bank_transactions):
    bank_transactions = list(dict.fromkeys(_as_list(bank_transactions)))
    rows = frappe.get_all(
        "Bank POS Transaction",
        filters={"name": ["in", bank_transactions]},
        fields=["name", "settlement_number", "settlement_date", "terminal_id"],
        limit_page_length=0,
    )
    settlements = {str(row.settlement_number or "").strip() for row in rows}
    if "" in settlements or len(settlements) != 1:
        frappe.throw(_("Finance clearance requires one non-empty Settlement Number."))

    groups = {
        (
            str(row.settlement_number or "").strip(),
            str(row.settlement_date or "").strip(),
            str(row.terminal_id or "").strip(),
        )
        for row in rows
    }
    if len(groups) != 1:
        frappe.throw(
            _(
                "This Settlement Number spans multiple settlement groups. "
                "Select one Settlement Date and Terminal ID group at a time."
            )
        )
    return bank_transactions


@frappe.whitelist()
def mark_selected_bank_transactions(bank_transactions, reason=None):
    bank_transactions = _validate_single_settlement(bank_transactions)
    return mark_bank_transactions(bank_transactions, reason)


@frappe.whitelist()
def reopen_selected_bank_transactions(bank_transactions):
    return reopen_bank_transactions(bank_transactions)


@frappe.whitelist()
def mark_selected_reconciliation_records(record_names, reason=None):
    _check_permission()
    record_names = _as_list(record_names)
    rows = frappe.get_all(
        "POS Reconciliation Record",
        filters={"name": ["in", record_names]},
        fields=["name", "bank_transaction", "match_status"],
        limit_page_length=0,
    )
    invalid = [row.name for row in rows if row.match_status != "Bank Only" or not row.bank_transaction]
    if invalid:
        frappe.throw(_("Manual clearing is allowed only for Bank Only records."))
    return mark_bank_transactions([row.bank_transaction for row in rows], reason)


@frappe.whitelist()
def reopen_selected_reconciliation_records(record_names):
    _check_permission()
    record_names = _as_list(record_names)
    rows = frappe.get_all(
        "POS Reconciliation Record",
        filters={"name": ["in", record_names]},
        fields=["bank_transaction"],
        limit_page_length=0,
    )
    return reopen_bank_transactions([row.bank_transaction for row in rows if row.bank_transaction])
