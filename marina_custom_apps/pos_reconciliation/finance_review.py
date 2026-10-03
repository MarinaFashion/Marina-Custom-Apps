from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, cstr, getdate, now_datetime

from marina_custom_apps.pos_reconciliation.manual_clearance import (
    _check_permission,
    _clearance_doc,
    mark_bank_transactions,
)
from marina_custom_apps.pos_reconciliation.reconciliation_engine import (
    FINANCE_APPROVED,
    FINANCE_INVESTIGATE,
    FINANCE_PENDING,
    refresh_run_summary,
)

VALID_DECISIONS = {FINANCE_APPROVED, FINANCE_INVESTIGATE}
SETTINGS_DOCTYPE = "POS Reconciliation Settings"


def _as_list(value):
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except ValueError:
            return [value]
    return list(value or [])


def _settings_flags():
    defaults = {
        "allow_bulk_finance_review": 1,
    }
    if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
        return frappe._dict(defaults)
    values = frappe.get_single(SETTINGS_DOCTYPE)
    return frappe._dict({
        "allow_bulk_finance_review": cint(values.allow_bulk_finance_review),
    })


def _ensure_bulk_review_allowed():
    if not _settings_flags().allow_bulk_finance_review:
        frappe.throw(_("Bulk Finance review is disabled in POS Reconciliation Settings."))


def _review_record_rows(record_names, require_pending=False):
    record_names = list(dict.fromkeys(_as_list(record_names)))
    if not record_names:
        frappe.throw(_("Select at least one reconciliation record."))

    rows = frappe.get_all(
        "POS Reconciliation Record",
        filters={"name": ["in", record_names]},
        fields=[
            "name", "bank_transaction", "match_status", "resolution_status",
            "settlement_number", "settlement_date", "terminal_id", "run",
        ],
        limit_page_length=0,
    )
    invalid = [row.name for row in rows if row.match_status != "Bank Only" or not row.bank_transaction]
    if invalid:
        frappe.throw(_("Finance review actions are allowed only for Bank Only records."))

    if require_pending:
        not_pending = [row.name for row in rows if row.resolution_status != "Pending"]
        if not_pending:
            frappe.throw(_("Only pending Bank Only records can be selected for Finance review."))

    _validate_one_settlement_group(rows)
    return rows


def _validate_one_settlement_group(rows):
    if not rows:
        return

    settlements = {cstr(row.settlement_number).strip() for row in rows}
    if "" in settlements or len(settlements) != 1:
        frappe.throw(_("Finance review requires one non-empty Settlement Number."))

    groups = {
        (
            cstr(row.settlement_number).strip(),
            cstr(getattr(row, "settlement_date", None)).strip(),
            cstr(getattr(row, "terminal_id", None)).strip(),
        )
        for row in rows
    }
    if len(groups) != 1:
        frappe.throw(
            _(
                "This Settlement Number spans multiple settlement groups. "
                "Narrow the review by Settlement Date and Terminal ID before approval."
            )
        )


def _mark_needs_investigation(bank_transactions, note=None):
    _check_permission()
    bank_transactions = list(dict.fromkeys(_as_list(bank_transactions)))
    if not bank_transactions:
        return {"updated": 0, "affected_runs": 0}

    note = cstr(note).strip() or _("Needs investigation")
    now = now_datetime()
    affected_runs = set()
    updated = 0

    for bank_name in bank_transactions:
        if not frappe.db.exists("Bank POS Transaction", bank_name):
            continue

        doc = _clearance_doc(bank_name)
        was_active = cint(doc.active)
        doc.bank_transaction = bank_name
        doc.active = 0
        doc.reason = note
        doc.finance_review_status = FINANCE_INVESTIGATE
        doc.finance_review_note = note
        doc.finance_reviewed_by = frappe.session.user
        doc.finance_reviewed_on = now
        if was_active:
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
                    "finance_review_status": FINANCE_INVESTIGATE,
                    "finance_reviewed_by": frappe.session.user,
                    "finance_reviewed_on": now,
                    "finance_review_note": note,
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


def _reset_review(bank_transactions):
    _check_permission()
    bank_transactions = list(dict.fromkeys(_as_list(bank_transactions)))
    now = now_datetime()
    affected_runs = set()
    updated = 0

    for bank_name in bank_transactions:
        clearance_name = frappe.db.get_value(
            "POS Bank Manual Clearance",
            {"bank_transaction": bank_name},
            "name",
        )
        if clearance_name:
            doc = frappe.get_doc("POS Bank Manual Clearance", clearance_name)
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

    return {"updated": updated, "affected_runs": len(affected_runs)}


def review_bank_transactions(bank_transactions, decision, note=None):
    decision = cstr(decision).strip()
    if decision not in VALID_DECISIONS:
        frappe.throw(_("Invalid Finance review decision."))

    if decision == FINANCE_APPROVED:
        return mark_bank_transactions(bank_transactions, note or _("Finance checked and approved against books"))
    return _mark_needs_investigation(bank_transactions, note)


def _filtered_bank_only_rows(
    run_name,
    settlement_number,
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
    if not run_name:
        frappe.throw(_("Reconciliation Run is required."))

    settlement_number = cstr(settlement_number).strip()
    if not settlement_number:
        frappe.throw(_("Settlement Number is required for bulk Finance review."))

    filters = {
        "run": run_name,
        "match_status": "Bank Only",
        "resolution_status": "Pending",
    }
    if settlement_number:
        filters["settlement_number"] = settlement_number

    if from_date and to_date:
        from_date, to_date = getdate(from_date), getdate(to_date)
        if from_date > to_date:
            frappe.throw(_("From Date cannot be after To Date."))
        filters["transaction_date"] = ["between", [from_date, to_date]]
    elif from_date:
        filters["transaction_date"] = [">=", getdate(from_date)]
    elif to_date:
        filters["transaction_date"] = ["<=", getdate(to_date)]

    for fieldname, value in {
        "settlement_date": settlement_date,
        "pos_profile": pos_profile,
        "terminal_id": terminal_id,
        "card_type": card_type,
        "finance_review_status": finance_review_status,
    }.items():
        value = cstr(value).strip()
        if value:
            filters[fieldname] = value

    if before_integration not in (None, "", "All"):
        filters["before_integration"] = cint(before_integration)

    search = cstr(search).strip()
    or_filters = None
    if search:
        like = ["like", f"%{search}%"]
        or_filters = {
            "bank_transaction": like,
            "terminal_id": like,
            "pos_profile": like,
            "card_type": like,
            "settlement_number": like,
            "finance_review_note": like,
        }

    rows = frappe.get_all(
        "POS Reconciliation Record",
        filters=filters,
        or_filters=or_filters,
        fields=["name", "bank_transaction", "settlement_number", "settlement_date", "terminal_id"],
        limit_page_length=0,
    )
    if rows:
        _validate_one_settlement_group(rows)
    return rows


@frappe.whitelist()
def review_selected_records(record_names, decision, note=None):
    _ensure_bulk_review_allowed()
    rows = _review_record_rows(record_names, require_pending=True)
    return review_bank_transactions([row.bank_transaction for row in rows], decision, note)


@frappe.whitelist()
def reset_selected_records(record_names):
    _ensure_bulk_review_allowed()
    rows = _review_record_rows(record_names, require_pending=False)
    return _reset_review([row.bank_transaction for row in rows])


@frappe.whitelist()
def review_filtered_bank_only(
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
    _check_permission()
    _ensure_bulk_review_allowed()
    rows = _filtered_bank_only_rows(
        run_name,
        settlement_number,
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
    if not rows:
        return {"updated": 0, "affected_runs": 0}
    return review_bank_transactions([row.bank_transaction for row in rows], decision, note)
