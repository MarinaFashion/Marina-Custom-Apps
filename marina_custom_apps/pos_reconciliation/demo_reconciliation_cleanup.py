"""Explicit, DEMO-ONLY cleanup of derived legacy POS reconciliation data.

Does not remove imported Bank POS Transactions, Marina Bank Statement
Transactions, or import batches. Not part of the Single-DocType migration.
"""

from __future__ import annotations

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import cstr, now_datetime

DEMO_SITE = "marinademo.frappe.cloud"
CONFIRMATION = "CLEAR DEMO POS RECONCILIATION"
STATUS_CACHE = "marina:demo_pos_reconciliation_cleanup:status"

SETTLEMENT = "POS Bank Settlement"
RECORD = "POS Reconciliation Record"
CLEARANCE = "POS Bank Manual Clearance"
STATEMENT = "Marina Bank Statement Transaction"


def _guard_demo():
    if cstr(frappe.local.site) != DEMO_SITE:
        frappe.throw(_("This destructive maintenance operation is disabled outside the Marina Demo site."), frappe.PermissionError)
    if "System Manager" not in frappe.get_roles(frappe.session.user):
        frappe.throw(_("Only System Manager can perform Demo POS reconciliation cleanup."), frappe.PermissionError)


def _all_rows(doctype, fields):
    return frappe.get_all(
        doctype, fields=fields,
        order_by="name asc", limit_page_length=0,
    )


def _source_links():
    # The old POS integration may link statement transactions from either direction.
    return frappe.db.sql(
        """
        SELECT name, modified, pos_bank_settlement, pos_reconciliation_run,
               is_pos_statement_line, bank_statement_reconciliation_match,
               reconciliation_status, debit, credit
        FROM `tabMarina Bank Statement Transaction`
        WHERE COALESCE(pos_bank_settlement, '') != ''
           OR COALESCE(pos_reconciliation_run, '') != ''
        ORDER BY name
        """,
        as_dict=True,
    )


def _linked(doctype, filter_values):
    return bool(frappe.db.exists(doctype, filter_values))


def _in_chunks(items, size=300):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _blockers(statements, settlements, records, postings):
    reasons = []
    if postings:
        reasons.append(_("POS Accounting Posting contains {0} document(s), including drafts.").format(len(postings)))
    if frappe.db.count("POS Accounting Posting Item"):
        reasons.append(_("POS Accounting Posting Item data exists."))
    if _linked("Marina Bank Statement Allocation", {"reference_doctype": RECORD}):
        reasons.append(_("Bank Statement Allocation rows reference reconciliation results."))
    if _linked("Bank POS Transaction", {"journal_entry": ["is", "set"]}):
        reasons.append(_("A Bank POS Transaction is linked to a Journal Entry."))
    if _linked("Bank POS Transaction", {"accounting_posting": ["is", "set"]}):
        reasons.append(_("A Bank POS Transaction is linked to a POS Accounting Posting."))
    if _linked("Bank POS Transaction", {
        "accounting_status": ["in", [
            "Posted", "Draft Created", "Draft - Review Required", "Posted - Review Required",
        ]],
    }):
        reasons.append(_("Bank POS Transactions include previously posted or drafted accounting status."))
    protected_records = [
        row.name for row in records
        if row.journal_entry or row.accounting_posting
        or cstr(row.accounting_status) in {
            "Posted", "Draft Created", "Draft - Review Required", "Posted - Review Required"
        }
    ]
    if protected_records:
        reasons.append(_("Reconciliation Records contain accounting evidence: {0}.").format(len(protected_records)))

    statement_names = [row.name for row in statements]
    if any(not row.is_pos_statement_line for row in statements):
        reasons.append(_("Some linked bank statement rows are not marked as POS lines."))
    if any(row.bank_statement_reconciliation_match for row in statements):
        reasons.append(_("Some linked POS statement rows also have Bank/GL reconciliation matches."))
    if any(cstr(row.reconciliation_status) == "Excluded" for row in statements):
        reasons.append(_("Some linked POS statement rows are Excluded."))

    for batch in _in_chunks(statement_names):
        if _linked("Marina Bank Statement Allocation", {
            "parenttype": STATEMENT, "parent": ["in", batch],
        }):
            reasons.append(_("Linked statement rows have allocations; cleanup would alter accounting evidence."))
            break
    for batch in _in_chunks(statement_names):
        if _linked("Bank Statement Reconciliation Bank Row", {
            "statement_transaction": ["in", batch],
        }):
            reasons.append(_("Linked statement rows appear in a Bank/GL reconciliation match."))
            break

    if frappe.db.exists("POS Reconciliation Run", {
        "execution_status": ["in", ["Queued", "Running"]]
    }):
        reasons.append(_("An old POS Reconciliation Run is queued or running."))

    settlement_names = {row.name for row in settlements}
    unknown = [row.name for row in statements if row.pos_bank_settlement and row.pos_bank_settlement not in settlement_names]
    if unknown:
        reasons.append(_("Bank statement rows reference missing POS Settlements: {0}.").format(len(unknown)))

    return reasons


def _snapshot():
    settlements = _all_rows(SETTLEMENT, ["name", "modified"])
    records = _all_rows(RECORD, [
        "name", "modified", "accounting_status", "accounting_posting", "journal_entry",
    ])
    clearances = _all_rows(CLEARANCE, ["name", "modified"])
    statements = _source_links()
    postings = _all_rows("POS Accounting Posting", ["name", "modified"])
    blockers = _blockers(statements, settlements, records, postings)
    summary = {
        "settlements_to_delete": len(settlements),
        "reconciliation_records_to_delete": len(records),
        "finance_clearances_to_delete": len(clearances),
        "statement_links_to_reset": len(statements),
        "accounting_postings_found": len(postings),
        "imported_pos_transactions_preserved": frappe.db.count("Bank POS Transaction"),
        "imported_statement_rows_preserved": frappe.db.count(STATEMENT),
    }
    # Snapshot digest ensures an approval cannot silently apply to different records.
    inventory = {
        "settlements": [(row.name, str(row.modified)) for row in settlements],
        "records": [(row.name, str(row.modified)) for row in records],
        "clearances": [(row.name, str(row.modified)) for row in clearances],
        "statement_links": [
            (
                row.name, str(row.modified), row.pos_bank_settlement,
                row.pos_reconciliation_run, row.reconciliation_status,
                row.bank_statement_reconciliation_match, row.is_pos_statement_line,
                str(row.debit), str(row.credit),
            )
            for row in statements
        ],
        "postings": [(row.name, str(row.modified)) for row in postings],
    }
    signature = hashlib.sha256(
        json.dumps(inventory, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return {
        "summary": summary, "blockers": blockers,
        "signature": signature,
        "_settlements": settlements, "_records": records,
        "_clearances": clearances, "_statements": statements,
    }


@frappe.whitelist()
def preview_demo_reconciliation_cleanup():
    _guard_demo()
    snap = _snapshot()
    return {
        "summary": snap["summary"], "blockers": snap["blockers"],
        "signature": snap["signature"],
        "can_proceed": not snap["blockers"],
        "note": _("This will delete only derived Demo reconciliation results and clear POS-specific links on imported bank statement transactions. It will not delete imports or source transactions."),
    }


@frappe.whitelist()
def get_demo_reconciliation_cleanup_status():
    _guard_demo()
    return frappe.cache().get_value(STATUS_CACHE) or {"status": "Not Started"}


@frappe.whitelist()
def queue_demo_reconciliation_cleanup(confirmation, expected_signature):
    _guard_demo()
    if cstr(confirmation) != CONFIRMATION:
        frappe.throw(_("Type the exact confirmation phrase to proceed."))
    snap = _snapshot()
    if snap["blockers"]:
        frappe.throw(_("Demo cleanup refused: {0}").format("; ".join(snap["blockers"])))
    if snap["signature"] != cstr(expected_signature):
        frappe.throw(_("Data changed after preview. Refresh the preview and confirm again."))

    # Lock the queue request. This is not an accounting or import operation.
    frappe.db.sql(
        "SELECT name FROM `tabDocType` WHERE name = %s FOR UPDATE",
        (SETTLEMENT,),
    )
    active = frappe.cache().get_value(STATUS_CACHE) or {}
    if active.get("status") in {"Queued", "Running"}:
        frappe.throw(_("Another Demo POS cleanup is queued or running."))
    job_id = "marina-demo-pos-cleanup-" + now_datetime().strftime("%Y%m%d%H%M%S%f")
    frappe.cache().set_value(STATUS_CACHE, {
        "status": "Queued", "job_id": job_id, "summary": snap["summary"],
    }, expires_in_sec=7200)
    frappe.enqueue(
        "marina_custom_apps.pos_reconciliation.demo_reconciliation_cleanup.execute_demo_reconciliation_cleanup",
        queue="long", timeout=3600, job_id=job_id, enqueue_after_commit=True,
        expected_signature=snap["signature"],
    )
    return {"status": "Queued", "job_id": job_id, "summary": snap["summary"]}


def execute_demo_reconciliation_cleanup(expected_signature):
    """Long worker; transactional, fails closed if blockers or source links change."""
    _guard_demo()
    cache = frappe.cache()
    cache.set_value(STATUS_CACHE, {"status": "Running"}, expires_in_sec=7200)
    try:
        # Serialize cleanup against a second cleanup worker.
        frappe.db.sql(
            "SELECT name FROM `tabDocType` WHERE name = %s FOR UPDATE",
            (SETTLEMENT,),
        )
        snap = _snapshot()
        if snap["blockers"]:
            frappe.throw(_("Cleanup stopped: {0}").format("; ".join(snap["blockers"])))
        if snap["signature"] != cstr(expected_signature):
            frappe.throw(_("Cleanup source data changed since preview. No documents were removed."))

        # These statement rows are POS-derived evidence only; never delete sources.
        for row in snap["_statements"]:
            amount = abs(float(row.debit or 0)) or abs(float(row.credit or 0))
            frappe.db.set_value(
                STATEMENT, row.name,
                {
                    "pos_bank_settlement": None,
                    "pos_reconciliation_run": None,
                    "reconciliation_status": "Unreconciled",
                    "allocated_amount": 0,
                    "remaining_amount": amount,
                    "reconciled_on": None,
                    "reconciled_by": None,
                },
                update_modified=False,
            )

        # Break the other half of the circular reference before document deletion.
        for row in snap["_records"]:
            frappe.db.set_value(
                RECORD, row.name, {
                    "bank_statement_settlement": None,
                    "bank_statement_reconciliation": None,
                }, update_modified=False,
            )

        # Parent deletion automatically deletes the settlement's child evidence rows.
        # Do not force-delete: remaining unexpected links should abort the transaction.
        for row in snap["_settlements"]:
            frappe.delete_doc(SETTLEMENT, row.name, ignore_permissions=True)

        for row in snap["_records"]:
            frappe.delete_doc(RECORD, row.name, ignore_permissions=True)

        for row in snap["_clearances"]:
            frappe.delete_doc(CLEARANCE, row.name, ignore_permissions=True)

        remaining = {
            "settlements": frappe.db.count(SETTLEMENT),
            "reconciliation_records": frappe.db.count(RECORD),
            "finance_clearances": frappe.db.count(CLEARANCE),
        }
        if any(remaining.values()):
            frappe.throw(_("Cleanup incomplete. Transaction rolled back."))

        # Required for this maintenance worker; publish successful result atomically.
        frappe.db.commit()
        info = {
            "status": "Completed",
            "completed_on": str(now_datetime()),
            "cleared": snap["summary"],
        }
        cache.set_value(STATUS_CACHE, info, expires_in_sec=86400)
        return info
    except Exception:
        frappe.db.rollback()
        error = cstr(frappe.get_traceback())[-3500:]
        cache.set_value(STATUS_CACHE, {
            "status": "Failed",
            "completed_on": str(now_datetime()),
            "error": error,
        }, expires_in_sec=86400)
        frappe.log_error(message=error, title="Demo POS Reconciliation Cleanup Failed")
        raise
