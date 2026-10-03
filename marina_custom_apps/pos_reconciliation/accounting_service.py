from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, getdate, now_datetime

SETTINGS_DOCTYPE = "POS Reconciliation Settings"
RECORD_DOCTYPE = "POS Reconciliation Record"
BANK_DOCTYPE = "Bank POS Transaction"
POSTING_DOCTYPE = "POS Accounting Posting"
POSTING_ITEM_DOCTYPE = "POS Accounting Posting Item"
RUN_DOCTYPE = "POS Reconciliation Run"

ACCOUNTING_NOT_ELIGIBLE = "Not Eligible"
ACCOUNTING_PENDING = "Pending Accounting"
ACCOUNTING_DRAFT = "Draft Created"
ACCOUNTING_POSTED = "Posted"
ACCOUNTING_NO_CHARGES = "No Charges"
ACCOUNTING_DRAFT_REVIEW_REQUIRED = "Draft - Review Required"
ACCOUNTING_REVIEW_REQUIRED = "Posted - Review Required"

ACCOUNTING_STATUSES = (
    ACCOUNTING_NOT_ELIGIBLE,
    ACCOUNTING_PENDING,
    ACCOUNTING_DRAFT,
    ACCOUNTING_POSTED,
    ACCOUNTING_NO_CHARGES,
    ACCOUNTING_DRAFT_REVIEW_REQUIRED,
    ACCOUNTING_REVIEW_REQUIRED,
)

JOURNAL_ENTRY_MODE_DRAFT = "Draft"
JOURNAL_ENTRY_MODE_SUBMIT = "Submit"


def is_reconciliation_confirmed(match_status, resolution_status):
    """Accounting is allowed only after reconciliation has confirmed the bank transaction."""
    return cstr(match_status).strip() == "Matching" or cstr(resolution_status).strip() == "Manually Cleared"



def derive_accounting_status(
    confirmed,
    commission,
    vat,
    journal_entry_docstatus=None,
    has_journal_entry=False,
):
    """Return the independent accounting state for a bank POS transaction."""
    if has_journal_entry and cint(journal_entry_docstatus) == 1:
        return ACCOUNTING_POSTED if confirmed else ACCOUNTING_REVIEW_REQUIRED
    if has_journal_entry and cint(journal_entry_docstatus) == 0:
        return ACCOUNTING_DRAFT if confirmed else ACCOUNTING_DRAFT_REVIEW_REQUIRED

    if not confirmed:
        return ACCOUNTING_NOT_ELIGIBLE
    if abs(flt(commission, 2)) <= 0.005 and abs(flt(vat, 2)) <= 0.005:
        return ACCOUNTING_NO_CHARGES
    return ACCOUNTING_PENDING



def accounting_group_key(row, consolidate_profiles):
    """Group pending transactions by POS Profile only when consolidation is disabled."""
    if consolidate_profiles:
        return ("ALL",)
    return (cstr(row.pos_profile).strip(),)


def _check_permission(ptype="read"):
    if not frappe.has_permission(POSTING_DOCTYPE, ptype=ptype):
        frappe.throw(
            _("You are not permitted to {0} POS Accounting Posting.").format(ptype),
            frappe.PermissionError,
        )


def _check_run(run_name):
    if not run_name:
        frappe.throw(_("Reconciliation Run is required."))
    run = frappe.get_doc(RUN_DOCTYPE, run_name)
    run.check_permission("read")
    if run.status != "Completed":
        frappe.throw(_("Accounting entries can be created only from a completed reconciliation run."))
    return run


def get_accounting_settings(require_enabled=False):
    settings = frappe.get_single(SETTINGS_DOCTYPE)
    if require_enabled and not cint(settings.enable_accounting_posting):
        frappe.throw(_("POS accounting posting is disabled in POS Reconciliation Settings."))
    if require_enabled:
        validate_accounting_settings(settings)
    return settings



def validate_accounting_settings(settings):
    required = {
        "company": _("Company"),
        "commission_expense_account": _("Commission Expense Account"),
        "vat_input_account": _("VAT Input Account"),
        "default_offset_account": _("Bank Account"),
    }
    missing = [label for fieldname, label in required.items() if not cstr(settings.get(fieldname)).strip()]
    if missing:
        frappe.throw(_("Complete POS Reconciliation Settings before accounting posting: {0}").format(", ".join(missing)))

    creation_mode = cstr(settings.get("journal_entry_creation_mode") or JOURNAL_ENTRY_MODE_DRAFT).strip()
    if creation_mode not in {JOURNAL_ENTRY_MODE_DRAFT, JOURNAL_ENTRY_MODE_SUBMIT}:
        frappe.throw(_("Journal Entry Creation Mode must be Draft or Submit."))

    company_currency = frappe.db.get_value("Company", settings.company, "default_currency")
    if not company_currency:
        frappe.throw(_("Company {0} does not have a default currency.").format(settings.company))

    _validate_account(
        settings.commission_expense_account,
        settings.company,
        company_currency,
        _("Commission Expense Account"),
        required_root_type="Expense",
    )
    _validate_account(
        settings.vat_input_account,
        settings.company,
        company_currency,
        _("VAT Input Account"),
    )
    _validate_account(
        settings.default_offset_account,
        settings.company,
        company_currency,
        _("Bank Account"),
        required_account_type="Bank",
    )
    return settings


def _validate_account(account, company, company_currency, label, required_root_type=None, required_account_type=None):
    row = frappe.db.get_value(
        "Account",
        account,
        ["company", "is_group", "account_currency", "root_type", "account_type"],
        as_dict=True,
    )
    if not row:
        frappe.throw(_("{0} {1} does not exist.").format(label, account))
    if row.company != company:
        frappe.throw(_("{0} {1} belongs to {2}, not {3}.").format(label, account, row.company, company))
    if cint(row.is_group):
        frappe.throw(_("{0} {1} cannot be a group account.").format(label, account))
    account_currency = row.account_currency or company_currency
    if account_currency != company_currency:
        frappe.throw(
            _("{0} {1} uses currency {2}. POS accounting requires company-currency accounts ({3}).").format(
                label, account, account_currency, company_currency
            )
        )
    if required_root_type and row.root_type != required_root_type:
        frappe.throw(_("{0} {1} must have root type {2}.").format(label, account, required_root_type))
    if required_account_type and row.account_type != required_account_type:
        frappe.throw(_("{0} {1} must have account type {2}.").format(label, account, required_account_type))


def _chunks(values, size=500):
    values = list(values or [])
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _latest_records_for_banks(bank_names):
    """Return the latest reconciliation evidence for every bank transaction."""
    result = {}
    for chunk in _chunks(bank_names):
        rows = frappe.get_all(
            RECORD_DOCTYPE,
            filters={"bank_transaction": ["in", chunk]},
            fields=[
                "name",
                "bank_transaction",
                "match_status",
                "resolution_status",
                "last_reconciled_on",
                "modified",
            ],
            order_by="bank_transaction asc, last_reconciled_on desc, modified desc, name desc",
            limit_page_length=0,
        )
        for row in rows:
            if row.bank_transaction and row.bank_transaction not in result:
                result[row.bank_transaction] = row
    return result



def sync_accounting_status_for_bank_transactions(bank_transactions):
    """Synchronize the bank-level accounting sign and mirror it to reconciliation records."""
    bank_transactions = list(
        dict.fromkeys(
            cstr(value).strip()
            for value in bank_transactions or []
            if cstr(value).strip()
        )
    )
    if not bank_transactions:
        return {"updated": 0}

    updated = 0
    for chunk in _chunks(bank_transactions):
        bank_rows = frappe.get_all(
            BANK_DOCTYPE,
            filters={"name": ["in", chunk]},
            fields=[
                "name",
                "fee_amount",
                "vat_amount",
                "accounting_status",
                "accounting_posting",
                "journal_entry",
                "accounting_posted_by",
                "accounting_posted_on",
            ],
            limit_page_length=0,
        )
        latest_map = _latest_records_for_banks([row.name for row in bank_rows])
        journal_names = list({row.journal_entry for row in bank_rows if row.journal_entry})
        journal_status = {}
        if journal_names:
            journal_status = {
                row.name: cint(row.docstatus)
                for row in frappe.get_all(
                    "Journal Entry",
                    filters={"name": ["in", journal_names]},
                    fields=["name", "docstatus"],
                    limit_page_length=0,
                )
            }

        for bank in bank_rows:
            latest = latest_map.get(bank.name)
            confirmed = bool(
                latest
                and is_reconciliation_confirmed(
                    latest.match_status,
                    latest.resolution_status,
                )
            )
            has_journal_entry = bool(
                bank.journal_entry and bank.journal_entry in journal_status
            )
            status = derive_accounting_status(
                confirmed,
                bank.fee_amount,
                bank.vat_amount,
                journal_status.get(bank.journal_entry),
                has_journal_entry=has_journal_entry,
            )

            # A stale link to a deleted draft should not keep the transaction reserved.
            if bank.journal_entry and not has_journal_entry:
                bank.accounting_posting = None
                bank.journal_entry = None
                bank.accounting_posted_by = None
                bank.accounting_posted_on = None
                frappe.db.set_value(
                    BANK_DOCTYPE,
                    bank.name,
                    {
                        "accounting_posting": None,
                        "journal_entry": None,
                        "accounting_posted_by": None,
                        "accounting_posted_on": None,
                    },
                    update_modified=False,
                )

            if bank.accounting_status != status:
                frappe.db.set_value(
                    BANK_DOCTYPE,
                    bank.name,
                    "accounting_status",
                    status,
                    update_modified=False,
                )
                updated += 1

            frappe.db.sql(
                f"""
                UPDATE `tab{RECORD_DOCTYPE}`
                SET accounting_status=%s,
                    accounting_posting=%s,
                    journal_entry=%s,
                    accounting_posted_by=%s,
                    accounting_posted_on=%s
                WHERE bank_transaction=%s
                """,
                (
                    status,
                    bank.accounting_posting,
                    bank.journal_entry,
                    bank.accounting_posted_by,
                    bank.accounting_posted_on,
                    bank.name,
                ),
            )
    return {"updated": updated}


def sync_accounting_status_for_records(record_names):
    record_names = list(dict.fromkeys(record_names or []))
    if not record_names:
        return {"updated": 0}
    banks = [
        row.bank_transaction
        for row in frappe.get_all(
            RECORD_DOCTYPE,
            filters={"name": ["in", record_names]},
            fields=["bank_transaction"],
            limit_page_length=0,
        )
        if row.bank_transaction
    ]
    return sync_accounting_status_for_bank_transactions(banks)


def sync_run_accounting_status(run_name):
    banks = [
        row.bank_transaction
        for row in frappe.get_all(
            RECORD_DOCTYPE,
            filters={"run": run_name, "bank_transaction": ["is", "set"]},
            fields=["bank_transaction"],
            limit_page_length=0,
        )
        if row.bank_transaction
    ]
    return sync_accounting_status_for_bank_transactions(banks)


def sync_all_accounting_statuses():
    banks = [
        row.bank_transaction
        for row in frappe.get_all(
            RECORD_DOCTYPE,
            filters={"bank_transaction": ["is", "set"]},
            fields=["bank_transaction"],
            group_by="bank_transaction",
            limit_page_length=0,
        )
        if row.bank_transaction
    ]
    total = 0
    for chunk in _chunks(banks, 400):
        total += sync_accounting_status_for_bank_transactions(chunk).get("updated", 0)
    return {"banks": len(banks), "updated": total}



def _pending_rows_for_run(run_name, pos_profile=None):
    """Return the latest confirmed, unposted bank transactions in a completed run."""
    _check_run(run_name)
    sync_run_accounting_status(run_name)

    filters = {
        "run": run_name,
        "bank_transaction": ["is", "set"],
        "accounting_status": ACCOUNTING_PENDING,
    }
    rows = frappe.get_all(
        RECORD_DOCTYPE,
        filters=filters,
        fields=[
            "name",
            "bank_transaction",
            "pos_profile",
            "terminal_id",
            "card_type",
            "transaction_date",
            "match_status",
            "resolution_status",
        ],
        order_by="transaction_date asc, name asc",
        limit_page_length=0,
    )
    if not rows:
        return []

    latest_map = _latest_records_for_banks([row.bank_transaction for row in rows])
    current_rows = [
        row
        for row in rows
        if latest_map.get(row.bank_transaction)
        and latest_map[row.bank_transaction].name == row.name
    ]
    if not current_rows:
        return []

    bank_map = {
        row.name: row
        for row in frappe.get_all(
            BANK_DOCTYPE,
            filters={"name": ["in", [row.bank_transaction for row in current_rows]]},
            fields=[
                "name",
                "fee_amount",
                "vat_amount",
                "settlement_number",
                "settlement_date",
                "pos_profile",
                "accounting_status",
                "accounting_posting",
                "journal_entry",
            ],
            limit_page_length=0,
        )
    }

    output = []
    for record in current_rows:
        if not is_reconciliation_confirmed(
            record.match_status,
            record.resolution_status,
        ):
            continue

        bank = bank_map.get(record.bank_transaction)
        if not bank or bank.accounting_status != ACCOUNTING_PENDING:
            continue

        effective_profile = bank.pos_profile or record.pos_profile
        row = frappe._dict(
            name=record.name,
            bank_transaction=record.bank_transaction,
            pos_profile=effective_profile,
            terminal_id=record.terminal_id,
            card_type=record.card_type,
            transaction_date=record.transaction_date,
            settlement_number=cstr(bank.settlement_number).strip(),
            settlement_date=bank.settlement_date,
            commission_amount=flt(bank.fee_amount, 2),
            vat_amount=flt(bank.vat_amount, 2),
        )
        if pos_profile and row.pos_profile != pos_profile:
            continue
        output.append(row)
    return output


def _attach_cost_centers(rows, company):
    profiles = list({row.pos_profile for row in rows if row.pos_profile})
    profile_map = {}
    if profiles:
        profile_map = {
            row.name: row
            for row in frappe.get_all(
                "POS Profile",
                filters={"name": ["in", profiles]},
                fields=["name", "company", "cost_center"],
                limit_page_length=0,
            )
        }

    missing_profiles = []
    wrong_company = []
    for row in rows:
        if not row.pos_profile:
            missing_profiles.append(_("Bank transaction {0} has no POS Profile").format(row.bank_transaction))
            continue
        profile = profile_map.get(row.pos_profile)
        if not profile or not profile.cost_center:
            missing_profiles.append(row.pos_profile)
            continue
        if profile.company and profile.company != company:
            wrong_company.append(row.pos_profile)
            continue
        row.cost_center = profile.cost_center

    if missing_profiles:
        frappe.throw(
            _("Accounting posting requires POS Profile > Cost Center. Missing: {0}").format(
                ", ".join(sorted(set(missing_profiles)))
            )
        )
    if wrong_company:
        frappe.throw(
            _("These POS Profiles belong to a different company: {0}").format(
                ", ".join(sorted(set(wrong_company)))
            )
        )
    return rows



def get_accounting_filter_options(run_name):
    _check_permission("read")
    settings = get_accounting_settings(require_enabled=False)
    rows = _pending_rows_for_run(run_name)
    return {
        "enabled": cint(settings.enable_accounting_posting),
        "consolidate_pos_profiles": cint(
            settings.consolidate_pos_profiles_in_one_journal_entry
        ),
        "consolidate_bank_entries": cint(settings.consolidate_bank_entries),
        "journal_entry_creation_mode": cstr(
            settings.journal_entry_creation_mode or JOURNAL_ENTRY_MODE_DRAFT
        ),
        "pending_count": len(rows),
        "pos_profile_count": len({row.pos_profile for row in rows if row.pos_profile}),
        "commission": flt(sum(row.commission_amount for row in rows), 2),
        "vat": flt(sum(row.vat_amount for row in rows), 2),
        "total": flt(
            sum(row.commission_amount + row.vat_amount for row in rows),
            2,
        ),
        "transaction_from_date": min(
            (row.transaction_date for row in rows if row.transaction_date),
            default=None,
        ),
        "transaction_to_date": max(
            (row.transaction_date for row in rows if row.transaction_date),
            default=None,
        ),
    }



def _prepare_groups(run_name, pos_profile=None):
    settings = get_accounting_settings(require_enabled=True)
    rows = _pending_rows_for_run(
        run_name,
        pos_profile=pos_profile,
    )
    if not rows:
        frappe.throw(
            _("No confirmed transactions are pending accounting for the selected reconciliation run.")
        )

    for row in rows:
        if row.commission_amount < 0 or row.vat_amount < 0:
            frappe.throw(
                _("Negative commission/VAT is not supported. Bank transaction: {0}").format(
                    row.bank_transaction
                )
            )

    _attach_cost_centers(rows, settings.company)
    consolidate = cint(settings.consolidate_pos_profiles_in_one_journal_entry)
    groups = defaultdict(list)
    for row in rows:
        groups[accounting_group_key(row, consolidate)].append(row)
    return settings, groups



def get_accounting_preview(run_name, posting_date, pos_profile=None):
    _check_permission("read")
    if not posting_date:
        frappe.throw(_("Posting Date is required."))
    posting_date = getdate(posting_date)

    settings, groups = _prepare_groups(run_name, pos_profile)
    rows = [row for group in groups.values() for row in group]
    return {
        "posting_date": posting_date,
        "transaction_count": len(rows),
        "pos_profile_count": len({row.pos_profile for row in rows}),
        "journal_entry_count": len(groups),
        "commission": flt(sum(row.commission_amount for row in rows), 2),
        "vat": flt(sum(row.vat_amount for row in rows), 2),
        "total": flt(
            sum(row.commission_amount + row.vat_amount for row in rows),
            2,
        ),
        "consolidate_pos_profiles": cint(
            settings.consolidate_pos_profiles_in_one_journal_entry
        ),
        "consolidate_bank_entries": cint(settings.consolidate_bank_entries),
        "journal_entry_creation_mode": cstr(
            settings.journal_entry_creation_mode or JOURNAL_ENTRY_MODE_DRAFT
        ),
    }



def create_accounting_postings(run_name, posting_date, pos_profile=None):
    _check_permission("create")
    run = _check_run(run_name)
    if not posting_date:
        frappe.throw(_("Posting Date is required."))
    posting_date = getdate(posting_date)

    settings, groups = _prepare_groups(run_name, pos_profile)
    creation_mode = cstr(
        settings.journal_entry_creation_mode or JOURNAL_ENTRY_MODE_DRAFT
    ).strip()

    created = []
    for _key, rows in groups.items():
        posting = frappe.new_doc(POSTING_DOCTYPE)
        posting.company = settings.company
        posting.source_run = run.name
        posting.posting_date = posting_date
        posting.consolidate_pos_profiles = cint(
            settings.consolidate_pos_profiles_in_one_journal_entry
        )
        posting.consolidate_bank_entries = cint(settings.consolidate_bank_entries)
        posting.journal_entry_creation_mode = creation_mode
        posting.bank_account = settings.default_offset_account
        posting.commission_expense_account = settings.commission_expense_account
        posting.vat_input_account = settings.vat_input_account

        settlement_numbers = {
            cstr(row.settlement_number).strip()
            for row in rows
            if cstr(row.settlement_number).strip()
        }
        settlement_dates = {
            getdate(row.settlement_date)
            for row in rows
            if row.settlement_date
        }
        posting.settlement_number = (
            next(iter(settlement_numbers))
            if len(settlement_numbers) == 1
            else None
        )
        posting.settlement_date = (
            next(iter(settlement_dates))
            if len(settlement_dates) == 1
            else None
        )

        for row in rows:
            posting.append(
                "items",
                {
                    "reconciliation_record": row.name,
                    "bank_transaction": row.bank_transaction,
                    "transaction_date": row.transaction_date,
                    "settlement_number": row.settlement_number,
                    "settlement_date": row.settlement_date,
                    "pos_profile": row.pos_profile,
                    "cost_center": row.cost_center,
                    "terminal_id": row.terminal_id,
                    "card_type": row.card_type,
                    "commission_amount": row.commission_amount,
                    "vat_amount": row.vat_amount,
                },
            )

        posting.insert()
        posting.submit()
        journal_docstatus = (
            frappe.db.get_value("Journal Entry", posting.journal_entry, "docstatus")
            if posting.journal_entry
            else None
        )
        created.append(
            {
                "posting": posting.name,
                "journal_entry": posting.journal_entry,
                "journal_entry_docstatus": cint(journal_docstatus),
                "transaction_count": posting.transaction_count,
                "commission": flt(posting.total_commission, 2),
                "vat": flt(posting.total_vat, 2),
            }
        )

    return {
        "posting_count": len(created),
        "postings": created,
        "transaction_count": sum(row["transaction_count"] for row in created),
        "commission": flt(sum(row["commission"] for row in created), 2),
        "vat": flt(sum(row["vat"] for row in created), 2),
        "journal_entry_creation_mode": creation_mode,
    }



def validate_posting_document(doc):
    if not doc.company or not doc.posting_date:
        frappe.throw(_("Company and Posting Date are required."))
    if not doc.items:
        frappe.throw(_("POS Accounting Posting requires at least one transaction."))

    settings = frappe._dict(
        company=doc.company,
        commission_expense_account=doc.commission_expense_account,
        vat_input_account=doc.vat_input_account,
        default_offset_account=doc.bank_account,
        journal_entry_creation_mode=doc.journal_entry_creation_mode
        or JOURNAL_ENTRY_MODE_DRAFT,
    )
    validate_accounting_settings(settings)

    seen = set()
    profiles = set()
    total_commission = 0.0
    total_vat = 0.0
    settlement_numbers = set()
    settlement_dates = set()

    for item in doc.items:
        if not item.reconciliation_record or not item.bank_transaction:
            frappe.throw(
                _("Every posting item requires Reconciliation Record and Bank POS Transaction.")
            )
        if item.bank_transaction in seen:
            frappe.throw(
                _("Bank transaction {0} appears more than once in the posting.").format(
                    item.bank_transaction
                )
            )
        seen.add(item.bank_transaction)
        if item.pos_profile:
            profiles.add(item.pos_profile)
        if cstr(item.settlement_number).strip():
            settlement_numbers.add(cstr(item.settlement_number).strip())
        if item.settlement_date:
            settlement_dates.add(getdate(item.settlement_date))
        total_commission += flt(item.commission_amount, 2)
        total_vat += flt(item.vat_amount, 2)

    if not cint(doc.consolidate_pos_profiles) and len(profiles) > 1:
        frappe.throw(_("This posting is configured for one POS Profile only."))

    doc.settlement_number = (
        next(iter(settlement_numbers))
        if len(settlement_numbers) == 1
        else None
    )
    doc.settlement_date = (
        next(iter(settlement_dates))
        if len(settlement_dates) == 1
        else None
    )
    doc.total_commission = flt(total_commission, 2)
    doc.total_vat = flt(total_vat, 2)
    doc.total_credit = flt(total_commission + total_vat, 2)
    doc.transaction_count = len(doc.items)
    doc.pos_profile_count = len(profiles)
    if doc.docstatus == 0:
        doc.posting_status = "Draft"



def validate_posting_before_submit(doc):
    validate_posting_document(doc)
    current_settings = get_accounting_settings(require_enabled=True)
    _check_run(doc.source_run)

    expected = {
        "company": current_settings.company,
        "commission_expense_account": current_settings.commission_expense_account,
        "vat_input_account": current_settings.vat_input_account,
        "bank_account": current_settings.default_offset_account,
    }
    for fieldname, value in expected.items():
        if cstr(doc.get(fieldname)).strip() != cstr(value).strip():
            frappe.throw(
                _(
                    "POS Reconciliation Settings changed after this posting was prepared. "
                    "Recreate the posting before submit."
                )
            )

    if cint(doc.consolidate_pos_profiles) != cint(
        current_settings.consolidate_pos_profiles_in_one_journal_entry
    ):
        frappe.throw(
            _("POS Profile consolidation setting changed. Recreate the posting before submit.")
        )
    if cint(doc.consolidate_bank_entries) != cint(
        current_settings.consolidate_bank_entries
    ):
        frappe.throw(
            _("Bank entry consolidation setting changed. Recreate the posting before submit.")
        )
    if cstr(doc.journal_entry_creation_mode).strip() != cstr(
        current_settings.journal_entry_creation_mode
        or JOURNAL_ENTRY_MODE_DRAFT
    ).strip():
        frappe.throw(
            _("Journal Entry Creation Mode changed. Recreate the posting before submit.")
        )

    _validate_posting_sources(
        doc,
        allowed_accounting_statuses={ACCOUNTING_PENDING},
        require_linked_posting=False,
    )



def _transaction_reference_text(names, limit=20):
    names = [cstr(name).strip() for name in names if cstr(name).strip()]
    if len(names) <= limit:
        return ", ".join(names)
    shown = ", ".join(names[:limit])
    return _("{0} (+{1} more)").format(shown, len(names) - limit)


def _profile_summaries(posting_doc):
    summaries = {}
    for item in posting_doc.items:
        key = (
            cstr(item.pos_profile).strip(),
            cstr(item.cost_center).strip(),
        )
        if key not in summaries:
            summaries[key] = frappe._dict(
                pos_profile=key[0],
                cost_center=key[1],
                commission=0.0,
                vat=0.0,
                transaction_names=[],
                transaction_dates=[],
            )
        summary = summaries[key]
        summary.commission += flt(item.commission_amount, 2)
        summary.vat += flt(item.vat_amount, 2)
        summary.transaction_names.append(item.bank_transaction)
        if item.transaction_date:
            summary.transaction_dates.append(getdate(item.transaction_date))
    return [summaries[key] for key in sorted(summaries)]


def _journal_entry_description(posting_doc, summaries):
    all_transactions = [
        item.bank_transaction
        for item in posting_doc.items
        if item.bank_transaction
    ]
    transaction_dates = [
        getdate(item.transaction_date)
        for item in posting_doc.items
        if item.transaction_date
    ]
    settlement_numbers = sorted(
        {
            cstr(item.settlement_number).strip()
            for item in posting_doc.items
            if cstr(item.settlement_number).strip()
        }
    )
    profiles = [summary.pos_profile for summary in summaries if summary.pos_profile]

    date_range = "—"
    if transaction_dates:
        date_range = "{0} to {1}".format(
            min(transaction_dates),
            max(transaction_dates),
        )

    settlement_text = (
        ", ".join(settlement_numbers[:10])
        if settlement_numbers
        else "—"
    )
    if len(settlement_numbers) > 10:
        settlement_text += _(" (+{0} more)").format(len(settlement_numbers) - 10)

    return _(
        "POS bank commission and VAT posting | Posting: {0} | Reconciliation Run: {1} | "
        "Posting Date: {2} | Transactions: {3} | Transaction Date Range: {4} | "
        "POS Profiles: {5} | Settlements: {6} | Bank POS Transactions: {7}"
    ).format(
        posting_doc.name,
        posting_doc.source_run,
        posting_doc.posting_date,
        len(all_transactions),
        date_range,
        ", ".join(profiles) or "—",
        settlement_text,
        _transaction_reference_text(all_transactions),
    )


def _profile_line_remark(summary, label):
    return _(
        "{0} | POS Profile: {1} | Cost Center: {2} | Transactions: {3} | "
        "Bank POS Transactions: {4}"
    ).format(
        label,
        summary.pos_profile or "—",
        summary.cost_center or "—",
        len(summary.transaction_names),
        _transaction_reference_text(summary.transaction_names, limit=12),
    )


def _validate_posting_sources(
    posting_doc,
    allowed_accounting_statuses,
    require_linked_posting,
):
    bank_names = [item.bank_transaction for item in posting_doc.items]
    if not bank_names:
        frappe.throw(_("POS Accounting Posting has no Bank POS Transactions."))

    placeholders = ", ".join(["%s"] * len(bank_names))
    frappe.db.sql(
        f"SELECT name FROM `tab{BANK_DOCTYPE}` WHERE name IN ({placeholders}) FOR UPDATE",
        tuple(bank_names),
    )
    sync_accounting_status_for_bank_transactions(bank_names)
    latest_map = _latest_records_for_banks(bank_names)

    bank_map = {
        row.name: row
        for row in frappe.get_all(
            BANK_DOCTYPE,
            filters={"name": ["in", bank_names]},
            fields=[
                "name",
                "fee_amount",
                "vat_amount",
                "settlement_number",
                "settlement_date",
                "pos_profile",
                "accounting_status",
                "accounting_posting",
                "journal_entry",
            ],
            limit_page_length=0,
        )
    }

    for item in posting_doc.items:
        record = frappe.db.get_value(
            RECORD_DOCTYPE,
            item.reconciliation_record,
            [
                "name",
                "bank_transaction",
                "match_status",
                "resolution_status",
                "pos_profile",
            ],
            as_dict=True,
        )
        bank = bank_map.get(item.bank_transaction)
        if (
            not record
            or record.bank_transaction != item.bank_transaction
            or not bank
        ):
            frappe.throw(
                _("Posting item {0} no longer matches its reconciliation source.").format(
                    item.idx
                )
            )

        latest = latest_map.get(item.bank_transaction)
        if not latest or latest.name != item.reconciliation_record:
            frappe.throw(
                _(
                    "Reconciliation record {0} is not the latest reconciliation result "
                    "for bank transaction {1}."
                ).format(
                    item.reconciliation_record,
                    item.bank_transaction,
                )
            )

        if not is_reconciliation_confirmed(
            record.match_status,
            record.resolution_status,
        ):
            frappe.throw(
                _("Bank transaction {0} is no longer confirmed by reconciliation.").format(
                    item.bank_transaction
                )
            )

        if bank.accounting_status not in allowed_accounting_statuses:
            frappe.throw(
                _("Bank transaction {0} has accounting status {1}, expected one of: {2}.").format(
                    item.bank_transaction,
                    bank.accounting_status,
                    ", ".join(sorted(allowed_accounting_statuses)),
                )
            )

        if require_linked_posting:
            if bank.accounting_posting != posting_doc.name:
                frappe.throw(
                    _("Bank transaction {0} is linked to another accounting posting.").format(
                        item.bank_transaction
                    )
                )
            if bank.journal_entry != posting_doc.journal_entry:
                frappe.throw(
                    _("Bank transaction {0} is linked to another Journal Entry.").format(
                        item.bank_transaction
                    )
                )
        elif bank.accounting_posting or bank.journal_entry:
            frappe.throw(
                _("Bank transaction {0} is already reserved by an accounting posting.").format(
                    item.bank_transaction
                )
            )

        if (
            abs(flt(bank.fee_amount, 2) - flt(item.commission_amount, 2)) > 0.005
            or abs(flt(bank.vat_amount, 2) - flt(item.vat_amount, 2)) > 0.005
        ):
            frappe.throw(
                _("Commission/VAT changed for bank transaction {0}. Refresh before posting.").format(
                    item.bank_transaction
                )
            )

        if cstr(bank.settlement_number).strip() != cstr(
            item.settlement_number
        ).strip():
            frappe.throw(
                _("Settlement Number changed for bank transaction {0}. Refresh before posting.").format(
                    item.bank_transaction
                )
            )
        bank_settlement_date = (
            getdate(bank.settlement_date) if bank.settlement_date else None
        )
        item_settlement_date = (
            getdate(item.settlement_date) if item.settlement_date else None
        )
        if bank_settlement_date != item_settlement_date:
            frappe.throw(
                _("Settlement Date changed for bank transaction {0}. Refresh before posting.").format(
                    item.bank_transaction
                )
            )

        profile = bank.pos_profile or record.pos_profile
        cost_center = (
            frappe.db.get_value("POS Profile", profile, "cost_center")
            if profile
            else None
        )
        if not cost_center or cost_center != item.cost_center:
            frappe.throw(
                _("POS Profile cost center changed for {0}. Refresh before posting.").format(
                    profile or item.bank_transaction
                )
            )


def _mark_posting_journal_draft(posting_doc, journal_entry):
    bank_names = []
    for item in posting_doc.items:
        bank_names.append(item.bank_transaction)
        frappe.db.set_value(
            BANK_DOCTYPE,
            item.bank_transaction,
            {
                "accounting_status": ACCOUNTING_DRAFT,
                "accounting_posting": posting_doc.name,
                "journal_entry": journal_entry.name,
                "accounting_posted_by": None,
                "accounting_posted_on": None,
            },
            update_modified=False,
        )
    sync_accounting_status_for_bank_transactions(bank_names)


def create_journal_entry(posting_doc):
    validate_posting_before_submit(posting_doc)
    summaries = _profile_summaries(posting_doc)

    je = frappe.new_doc("Journal Entry")
    je.voucher_type = "Bank Entry"
    je.company = posting_doc.company
    je.posting_date = posting_doc.posting_date
    je.cheque_no = posting_doc.name
    je.cheque_date = posting_doc.posting_date
    je.user_remark = _journal_entry_description(posting_doc, summaries)

    for summary in summaries:
        commission = flt(summary.commission, 2)
        vat = flt(summary.vat, 2)

        if commission:
            je.append(
                "accounts",
                {
                    "account": posting_doc.commission_expense_account,
                    "debit_in_account_currency": commission,
                    "exchange_rate": 1,
                    "cost_center": summary.cost_center,
                    "user_remark": _profile_line_remark(
                        summary,
                        _("POS bank commission"),
                    ),
                },
            )

        if vat:
            je.append(
                "accounts",
                {
                    "account": posting_doc.vat_input_account,
                    "debit_in_account_currency": vat,
                    "exchange_rate": 1,
                    "cost_center": summary.cost_center,
                    "user_remark": _profile_line_remark(
                        summary,
                        _("VAT on POS bank commission"),
                    ),
                },
            )

    if cint(posting_doc.consolidate_bank_entries):
        if flt(posting_doc.total_commission, 2):
            je.append(
                "accounts",
                {
                    "account": posting_doc.bank_account,
                    "credit_in_account_currency": flt(
                        posting_doc.total_commission,
                        2,
                    ),
                    "exchange_rate": 1,
                    "user_remark": _(
                        "Bank charge - POS commission | {0} transactions / {1} POS Profiles"
                    ).format(
                        posting_doc.transaction_count,
                        posting_doc.pos_profile_count,
                    ),
                },
            )
        if flt(posting_doc.total_vat, 2):
            je.append(
                "accounts",
                {
                    "account": posting_doc.bank_account,
                    "credit_in_account_currency": flt(
                        posting_doc.total_vat,
                        2,
                    ),
                    "exchange_rate": 1,
                    "user_remark": _(
                        "Bank charge - VAT on POS commission | {0} transactions / {1} POS Profiles"
                    ).format(
                        posting_doc.transaction_count,
                        posting_doc.pos_profile_count,
                    ),
                },
            )
    else:
        for summary in summaries:
            commission = flt(summary.commission, 2)
            vat = flt(summary.vat, 2)
            if commission:
                je.append(
                    "accounts",
                    {
                        "account": posting_doc.bank_account,
                        "credit_in_account_currency": commission,
                        "exchange_rate": 1,
                        "user_remark": _(
                            "Bank charge - POS commission | POS Profile: {0} | Cost Center: {1}"
                        ).format(
                            summary.pos_profile or "—",
                            summary.cost_center or "—",
                        ),
                    },
                )
            if vat:
                je.append(
                    "accounts",
                    {
                        "account": posting_doc.bank_account,
                        "credit_in_account_currency": vat,
                        "exchange_rate": 1,
                        "user_remark": _(
                            "Bank charge - VAT on POS commission | POS Profile: {0} | Cost Center: {1}"
                        ).format(
                            summary.pos_profile or "—",
                            summary.cost_center or "—",
                        ),
                    },
                )

    if not je.accounts:
        frappe.throw(_("No commission or VAT amount is available for Journal Entry."))

    je.insert()
    frappe.db.set_value(
        POSTING_DOCTYPE,
        posting_doc.name,
        "journal_entry",
        je.name,
        update_modified=False,
    )
    posting_doc.journal_entry = je.name
    _mark_posting_journal_draft(posting_doc, je)

    if (
        cstr(posting_doc.journal_entry_creation_mode).strip()
        == JOURNAL_ENTRY_MODE_SUBMIT
    ):
        je.submit()

    return je



def mark_posting_posted(posting_doc, journal_entry):
    now = now_datetime()
    user = frappe.session.user
    bank_names = []
    for item in posting_doc.items:
        bank_names.append(item.bank_transaction)
        frappe.db.set_value(
            BANK_DOCTYPE,
            item.bank_transaction,
            {
                "accounting_status": ACCOUNTING_POSTED,
                "accounting_posting": posting_doc.name,
                "journal_entry": journal_entry.name,
                "accounting_posted_by": user,
                "accounting_posted_on": now,
            },
            update_modified=False,
        )

    frappe.db.set_value(
        POSTING_DOCTYPE,
        posting_doc.name,
        {
            "posting_status": "Posted",
            "posted_by": user,
            "posted_on": now,
        },
        update_modified=False,
    )
    sync_accounting_status_for_bank_transactions(bank_names)
    return now


def release_posting(posting_name, journal_entry=None):
    items = frappe.get_all(
        POSTING_ITEM_DOCTYPE,
        filters={"parent": posting_name, "parenttype": POSTING_DOCTYPE},
        fields=["bank_transaction"],
        limit_page_length=0,
    )
    bank_names = [row.bank_transaction for row in items if row.bank_transaction]
    for bank_name in bank_names:
        active_posting = frappe.db.get_value(BANK_DOCTYPE, bank_name, "accounting_posting")
        if active_posting == posting_name:
            frappe.db.set_value(
                BANK_DOCTYPE,
                bank_name,
                {
                    "accounting_posting": None,
                    "journal_entry": None,
                    "accounting_posted_by": None,
                    "accounting_posted_on": None,
                },
                update_modified=False,
            )
    sync_accounting_status_for_bank_transactions(bank_names)



def _get_posting_for_journal(journal_entry_name):
    posting_name = frappe.db.get_value(
        POSTING_DOCTYPE,
        {"journal_entry": journal_entry_name},
        "name",
    )
    if not posting_name:
        return None
    return frappe.get_doc(POSTING_DOCTYPE, posting_name)


def validate_generated_journal_entry_before_submit(doc, method=None):
    posting = _get_posting_for_journal(doc.name)
    if not posting:
        return
    _validate_posting_sources(
        posting,
        allowed_accounting_statuses={
            ACCOUNTING_DRAFT,
            ACCOUNTING_DRAFT_REVIEW_REQUIRED,
        },
        require_linked_posting=True,
    )


def on_journal_entry_submit(doc, method=None):
    posting = _get_posting_for_journal(doc.name)
    if not posting:
        return
    mark_posting_posted(posting, doc)


def on_journal_entry_cancel(doc, method=None):
    posting = _get_posting_for_journal(doc.name)
    if not posting:
        return
    frappe.db.set_value(
        POSTING_DOCTYPE,
        posting.name,
        "posting_status",
        "Journal Entry Cancelled",
        update_modified=False,
    )
    release_posting(posting.name, doc.name)


def on_journal_entry_trash(doc, method=None):
    posting = _get_posting_for_journal(doc.name)
    if not posting:
        return
    frappe.db.set_value(
        POSTING_DOCTYPE,
        posting.name,
        "posting_status",
        "Journal Entry Deleted",
        update_modified=False,
    )
    release_posting(posting.name, doc.name)
