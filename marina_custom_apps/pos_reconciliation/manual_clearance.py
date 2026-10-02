from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from marina_custom_apps.pos_reconciliation.reconciliation_engine import refresh_run_summary


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
    _check_permission()
    bank_transactions = list(dict.fromkeys(_as_list(bank_transactions)))
    if not bank_transactions:
        return {"updated": 0}

    reason = (reason or _("Pre-integration transaction")).strip()
    now = now_datetime()
    affected_runs = set()

    for bank_name in bank_transactions:
        if not frappe.db.exists("Bank POS Transaction", bank_name):
            continue

        doc = _clearance_doc(bank_name)
        doc.bank_transaction = bank_name
        doc.active = 1
        doc.reason = reason
        doc.cleared_by = frappe.session.user
        doc.cleared_on = now
        doc.reopened_by = None
        doc.reopened_on = None
        doc.flags.ignore_permissions = True
        doc.save()

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
                    "manual_clearance_reason": reason,
                    "manual_cleared_by": frappe.session.user,
                    "manual_cleared_on": now,
                },
                update_modified=True,
            )
            affected_runs.add(row.run)

    for run_name in affected_runs:
        refresh_run_summary(run_name)

    return {"updated": len(bank_transactions), "affected_runs": len(affected_runs)}


def reopen_bank_transactions(bank_transactions):
    _check_permission()
    bank_transactions = list(dict.fromkeys(_as_list(bank_transactions)))
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
                    "manual_clearance_reason": None,
                    "manual_cleared_by": None,
                    "manual_cleared_on": None,
                },
                update_modified=True,
            )
            affected_runs.add(row.run)

    for run_name in affected_runs:
        refresh_run_summary(run_name)

    return {"updated": updated, "affected_runs": len(affected_runs)}


@frappe.whitelist()
def mark_selected_bank_transactions(bank_transactions, reason=None):
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
