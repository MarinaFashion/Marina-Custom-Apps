"""Demo-only reset of linked imported bank statement rows and reconciliation evidence.

Deletes linked Marina Bank Statement Transaction source rows only after:
- breaking the Bank Statement Reconciliation Match circular links,
- releasing Bank/GL reconciliation groups,
- removing POS Settlement statement-match child links,
- resetting affected POS Reconciliation Records.

Never touches Bank POS Transactions, GL Entries, or their accounting vouchers.
"""

from __future__ import annotations

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import cstr, flt, now_datetime

SITE = "marinademo.frappe.cloud"
PHRASE = "DELETE DEMO LINKED BANK STATEMENTS"
CACHE_KEY = "marina:demo:linked_bank_statement_reset"

STATEMENT = "Marina Bank Statement Transaction"
MATCH = "Bank Statement Reconciliation Match"
BANK_CHILD = "Bank Statement Reconciliation Bank Row"
SETTLEMENT = "POS Bank Settlement"
POS_CHILD = "POS Bank Settlement Statement Match"
RECORD = "POS Reconciliation Record"
ALLOC = "Marina Bank Statement Allocation"

PROTECTED_ACCOUNTING = {
    "Posted", "Draft Created", "Draft - Review Required", "Posted - Review Required"
}
PROTECTED_REVIEW = {"Checked & Approved", "Needs Investigation"}


def _site_guard():
    if cstr(frappe.local.site) != SITE:
        frappe.throw(_("Bank statement test-data reset is disabled outside Marina Demo."), frappe.PermissionError)
    if not frappe.get_meta("POS Reconciliation Run").issingle:
        frappe.throw(_("This utility requires the experimental Single reconciliation architecture."))


def _manager_guard():
    _site_guard()
    if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only System Manager may reset Demo bank reconciliation test data."), frappe.PermissionError)


def _rows(doctype, fields, filters=None):
    return frappe.get_all(
        doctype, fields=fields, filters=filters or {},
        order_by="name asc", limit_page_length=0,
    )


def _chunks(items, size=300):
    for idx in range(0, len(items), size):
        yield items[idx:idx + size]


def _linked_statements():
    return frappe.db.sql(
        """
        SELECT name, modified, bank_account, statement_import, is_pos_statement_line,
               reconciliation_status, debit, credit, pos_reconciliation_run,
               pos_bank_settlement, bank_statement_reconciliation_match
          FROM `tabMarina Bank Statement Transaction`
         WHERE COALESCE(pos_reconciliation_run, '') <> ''
            OR COALESCE(pos_bank_settlement, '') <> ''
            OR COALESCE(bank_statement_reconciliation_match, '') <> ''
         ORDER BY name
        """,
        as_dict=True,
    )


def _inventory():
    matches = _rows(MATCH, ["name", "modified", "bank_account"])
    match_children = _rows(BANK_CHILD, ["name", "parent", "statement_transaction"],
                           {"parenttype": MATCH})
    settlements_with_statement = _rows(
        POS_CHILD, ["name", "parent", "bank_transaction"],
        {"parenttype": SETTLEMENT},
    )
    linked = {row.name: row for row in _linked_statements()}
    source_ids = set(linked)
    source_ids.update(row.statement_transaction for row in match_children if row.statement_transaction)
    source_ids.update(row.bank_transaction for row in settlements_with_statement if row.bank_transaction)

    sources = {}
    for chunk in _chunks(sorted(source_ids)):
        for row in _rows(
            STATEMENT,
            ["name", "modified", "bank_account", "statement_import", "debit", "credit",
             "is_pos_statement_line", "reconciliation_status", "pos_reconciliation_run",
             "pos_bank_settlement", "bank_statement_reconciliation_match"],
            {"name": ["in", chunk]},
        ):
            sources[row.name] = row

    settlement_ids = {row.parent for row in settlements_with_statement}
    settlement_ids.update(row.pos_bank_settlement for row in sources.values() if row.pos_bank_settlement)
    settlements = {}
    for chunk in _chunks(sorted(settlement_ids)):
        for row in _rows(
            SETTLEMENT,
            ["name", "modified", "status", "bank_account",
             "gross_amount", "commission_amount", "vat_amount", "expected_net"],
            {"name": ["in", chunk]},
        ):
            settlements[row.name] = row

    record_fields = [
        "name", "modified", "bank_transaction", "bank_statement_settlement",
        "bank_statement_references", "accounting_status", "accounting_posting",
        "journal_entry", "finance_review_status", "resolution_status", "match_status",
    ]
    records = {}
    for chunk in _chunks(sorted(settlements)):
        for row in _rows(
            RECORD, record_fields,
            {"bank_statement_settlement": ["in", chunk]},
        ):
            records[row.name] = row

    # Some historical results refer to statements by their comma-separated
    # names without a POS Settlement link. Include these rows in the reset.
    if source_ids:
        for row in _rows(
            RECORD, record_fields,
            {"bank_statement_references": ["is", "set"]},
        ):
            referenced = {x.strip() for x in cstr(row.bank_statement_references).split(",")}
            if referenced.intersection(source_ids):
                records[row.name] = row

    # A source can also be referenced in a text list. Detect, but do not silently
    # rewrite unrelated records outside the linked settlement set.
    blockers = []
    if len(sources) != len(source_ids):
        blockers.append(_("Referenced Bank Statement Transactions are missing."))
    if len(settlements) != len(settlement_ids):
        blockers.append(_("One or more referenced POS Bank Settlements are missing."))
    matched = {row.name for row in matches}
    missing_matches = sorted({
        row.bank_statement_reconciliation_match for row in sources.values()
        if row.bank_statement_reconciliation_match and row.bank_statement_reconciliation_match not in matched
    })
    if missing_matches:
        blockers.append(_("Bank Statement source rows reference missing Bank/GL matches."))
    if any(not row.statement_transaction for row in match_children):
        blockers.append(_("Bank/GL match rows contain missing Bank Statement identifiers."))
    if any(not row.bank_transaction for row in settlements_with_statement):
        blockers.append(_("POS settlement rows contain missing Bank Statement identifiers."))
    if any(row.parent not in matched for row in match_children):
        blockers.append(_("Orphaned Bank/GL match child rows were found."))
    if any(row.parent not in settlements for row in settlements_with_statement):
        blockers.append(_("Orphaned POS settlement statement-match child rows were found."))

    # All saved Bank/GL matches must have valid source rows and consistent accounts.
    grouped = {}
    for row in match_children:
        grouped.setdefault(row.parent, []).append(row.statement_transaction)
        source = sources.get(row.statement_transaction)
        if source and source.bank_statement_reconciliation_match not in (None, "", row.parent):
            blockers.append(_("Conflicting Bank/GL match links were detected."))
    repeated = {}
    for child in match_children:
        repeated.setdefault(child.statement_transaction, set()).add(child.parent)
    if any(len(parents) > 1 for parents in repeated.values()):
        blockers.append(_("A Bank Statement Transaction appears in multiple Bank/GL groups."))

    for match in matches:
        if not grouped.get(match.name):
            blockers.append(_("Bank/GL match {0} has no source Bank rows.").format(match.name))
        if any(sources.get(name) and sources[name].bank_account != match.bank_account
               for name in grouped.get(match.name, [])):
            blockers.append(_("Bank/GL match {0} has a different Bank Account.").format(match.name))

    # Any source allocation, exclusion or separate reconciliation evidence
    # must be investigated rather than erased with this reset.
    for chunk in _chunks(sorted(source_ids)):
        if frappe.db.exists(ALLOC, {"parenttype": STATEMENT, "parent": ["in", chunk]}):
            blockers.append(_("Bank Statement allocations exist on targeted source rows."))
            break
    for chunk in _chunks(sorted(source_ids)):
        if frappe.db.exists("Bank Reconciliation Exclusion", {
            "source_type": "Bank Statement", "source_record": ["in", chunk],
        }):
            blockers.append(_("Bank Reconciliation Exclusion history references a targeted source."))
            break

    if any(cstr(x.reconciliation_status) == "Excluded" for x in sources.values()):
        blockers.append(_("Excluded Bank Statement Transactions cannot be deleted automatically."))
    if any(x.accounting_posting or x.journal_entry
           or cstr(x.accounting_status) in PROTECTED_ACCOUNTING
           or cstr(x.finance_review_status) in PROTECTED_REVIEW
           or cstr(x.resolution_status) == "Manually Cleared"
           for x in records.values()):
        blockers.append(_("Linked POS Reconciliation Records have manual/Finance/accounting evidence."))
    if frappe.db.count("POS Accounting Posting") or frappe.db.count("POS Accounting Posting Item"):
        blockers.append(_("POS Accounting Posting documents or child items exist; resolve them before a source reset."))
    if frappe.db.exists("Bank POS Transaction", {"journal_entry": ["is", "set"]}):
        blockers.append(_("Bank POS Transactions contain linked Journal Entries."))
    if frappe.db.exists("Bank POS Transaction", {"accounting_posting": ["is", "set"]}):
        blockers.append(_("Bank POS Transactions contain linked accounting postings."))

    current_state = frappe.db.get_single_value("POS Reconciliation Run", "execution_status")
    if current_state in {"Queued", "Running"}:
        blockers.append(_("The POS Reconciliation Single execution is Queued or Running."))

    summary = {
        "linked_bank_statement_transactions_to_delete": len(source_ids),
        "bank_gl_reconciliation_matches_to_delete": len(matches),
        "gl_rows_released": frappe.db.count(
            "Bank Statement Reconciliation GL Row", {"parenttype": MATCH}
        ),
        "pos_settlements_to_reset": len(settlements),
        "pos_reconciliation_records_to_reset": len(records),
        "imported_pos_transactions_preserved": frappe.db.count("Bank POS Transaction"),
        "unlinked_bank_statement_transactions_preserved": (
            frappe.db.count(STATEMENT) - len(source_ids)
        ),
    }
    evidence = {
        "matches": [(x.name, str(x.modified)) for x in matches],
        "bank_children": [(x.name, x.parent, x.statement_transaction) for x in match_children],
        "gl_children": [
            (x.name, x.parent, x.gl_entry)
            for x in _rows(
                "Bank Statement Reconciliation GL Row",
                ["name", "parent", "gl_entry"], {"parenttype": MATCH}
            )
        ],
        "settlement_children": [
            (x.name, x.parent, x.bank_transaction) for x in settlements_with_statement
        ],
        "sources": [
            (x.name, str(x.modified), x.bank_statement_reconciliation_match,
             x.pos_bank_settlement, x.pos_reconciliation_run, x.reconciliation_status)
            for x in sources.values()
        ],
        "settlements": [(x.name, str(x.modified)) for x in settlements.values()],
        "records": [
            (x.name, str(x.modified), x.match_status,
             x.bank_statement_settlement, x.bank_statement_references,
             x.finance_review_status, x.accounting_status)
            for x in records.values()
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return {
        "summary": summary,
        "blockers": sorted(set(blockers)),
        "fingerprint": fingerprint,
        "_source_ids": sorted(source_ids),
        "_matches": matches,
        "_settlements": settlements,
        "_records": records,
    }


@frappe.whitelist()
def preview_demo_bank_statement_reset():
    _manager_guard()
    snap = _inventory()
    return {
        "summary": snap["summary"], "blockers": snap["blockers"],
        "fingerprint": snap["fingerprint"],
        "can_proceed": not snap["blockers"] and bool(snap["_source_ids"]),
    }


@frappe.whitelist()
def get_demo_bank_statement_reset_status():
    _manager_guard()
    return frappe.cache().get_value(CACHE_KEY) or {"status": "Not Started"}


@frappe.whitelist()
def queue_demo_bank_statement_reset(confirmation, fingerprint):
    _manager_guard()
    if cstr(confirmation) != PHRASE:
        frappe.throw(_("Incorrect confirmation phrase."))
    frappe.db.sql(
        "SELECT name FROM `tabDocType` WHERE name IN (%s, %s) ORDER BY name FOR UPDATE",
        (STATEMENT, "POS Reconciliation Run"),
    )
    status = frappe.cache().get_value(CACHE_KEY) or {}
    if status.get("status") in {"Queued", "Running"}:
        frappe.throw(_("A Demo Bank Statement reset is already queued/running."))
    snap = _inventory()
    if snap["blockers"] or not snap["_source_ids"]:
        frappe.throw(_("Bank Statement reset is blocked or has no linked rows."))
    if snap["fingerprint"] != cstr(fingerprint):
        frappe.throw(_("Reset preview is stale. Reopen preview before confirming."))

    job_id = "marina-demo-bank-reset-" + now_datetime().strftime("%Y%m%d%H%M%S%f")
    frappe.cache().set_value(CACHE_KEY, {"status": "Queued", "job_id": job_id},
                             expires_in_sec=7200)
    frappe.enqueue(
        "marina_custom_apps.pos_reconciliation.demo_bank_statement_reset.execute_demo_bank_statement_reset",
        queue="long", timeout=3600, job_id=job_id,
        enqueue_after_commit=True, expected_fingerprint=snap["fingerprint"],
        requested_by=frappe.session.user,
    )
    return {"status": "Queued", "job_id": job_id, "summary": snap["summary"]}


def execute_demo_bank_statement_reset(expected_fingerprint, requested_by):
    """Atomic maintenance job. Never call directly from a web request."""
    _site_guard()
    cache = frappe.cache()
    cache.set_value(CACHE_KEY, {"status": "Running"}, expires_in_sec=7200)
    try:
        frappe.db.sql(
            "SELECT name FROM `tabDocType` WHERE name IN (%s, %s) ORDER BY name FOR UPDATE",
            (STATEMENT, "POS Reconciliation Run"),
        )
        snap = _inventory()
        # Prevent another reconciliation from modifying these particular
        # statement rows until our reset transaction finishes.
        for chunk in _chunks(snap["_source_ids"]):
            placeholders = ", ".join(["%s"] * len(chunk))
            frappe.db.sql(
                "SELECT name FROM `tabMarina Bank Statement Transaction` "
                f"WHERE name IN ({placeholders}) FOR UPDATE",
                tuple(chunk),
            )
        snap = _inventory()
        if snap["blockers"] or not snap["_source_ids"]:
            frappe.throw(_("Reset stopped: protected or no longer linked data."))
        if snap["fingerprint"] != cstr(expected_fingerprint):
            frappe.throw(_("Source data changed after confirmation; reset aborted."))

        # Clear outward links on statement sources to avoid the circular reference.
        for name in snap["_source_ids"]:
            frappe.db.set_value(STATEMENT, name, {
                "bank_statement_reconciliation_match": None,
                "pos_bank_settlement": None, "pos_reconciliation_run": None,
            }, update_modified=False)

        # Release GL entries by removing their saved match groups, never GL postings.
        for doc in snap["_matches"]:
            frappe.delete_doc(MATCH, doc.name, ignore_permissions=True)

        # Reset POS reconciliation evidence without deleting operational records.
        for row in snap["_records"].values():
            values = {
                "bank_statement_status": "Not Checked",
                "bank_statement_reconciliation": None,
                "bank_statement_settlement": None,
                "bank_statement_references": None,
                "bank_statement_checked_on": None,
            }
            if row.match_status == "Fully Matching":
                values.update(match_status="Matching Not Settled",
                              resolution_status="Pending")
            elif row.match_status == "Bank Only - Settled":
                values.update(match_status="Bank Only - Not Settled",
                              resolution_status="Pending")
            frappe.db.set_value(RECORD, row.name, values, update_modified=False)

        # Remove child pointers before source deletion; keep settlement transaction
        # evidence, but clear its statement component totals for the next rerun.
        for row in snap["_settlements"].values():
            settlement = frappe.get_doc(SETTLEMENT, row.name)
            settlement.set("statement_matches", [])
            settlement.statement_gross_amount = 0
            settlement.statement_commission_amount = 0
            settlement.statement_vat_amount = 0
            settlement.statement_net_amount = 0
            settlement.gross_difference = -flt(settlement.gross_amount, 2)
            settlement.commission_difference = -flt(settlement.commission_amount, 2)
            settlement.vat_difference = -flt(settlement.vat_amount, 2)
            settlement.net_difference = -flt(settlement.expected_net, 2)
            settlement.status = "ERP Settlement Only"
            settlement.save(ignore_permissions=True)

        # Delete only the previously reconciled *linked* imported statement rows.
        # Retain unrelated statement rows and all imported Bank POS Transactions.
        for name in snap["_source_ids"]:
            frappe.delete_doc(STATEMENT, name, ignore_permissions=True)

        for chunk in _chunks(snap["_source_ids"]):
            if frappe.db.exists(STATEMENT, {"name": ["in", chunk]}):
                frappe.throw(_("Some targeted statement rows remain. Rolling back reset."))
        if frappe.db.count(MATCH):
            frappe.throw(_("Some Bank/GL match groups remain. Rolling back reset."))

        # Durable evidence of who reset the Demo documents without exposing any
        # transaction values or creating accounting entries.
        frappe.logger("demo_bank_statement_reset").warning(
            "DEMO reset by %s: %s; inventory hash %s",
            requested_by, json.dumps(snap["summary"], sort_keys=True),
            snap["fingerprint"],
        )
        frappe.db.commit()
        result = {
            "status": "Completed", "completed_on": str(now_datetime()),
            "summary": snap["summary"], "requested_by": requested_by,
        }
        cache.set_value(CACHE_KEY, result, expires_in_sec=86400)
        return result
    except Exception:
        frappe.db.rollback()
        error = cstr(frappe.get_traceback())[-5000:]
        cache.set_value(CACHE_KEY, {
            "status": "Failed", "completed_on": str(now_datetime()),
            "error": error,
        }, expires_in_sec=86400)
        frappe.log_error(message=error, title="Demo Bank Statement Reset Failed")
        raise
