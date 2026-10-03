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
ACCOUNTING_POSTED = "Posted"
ACCOUNTING_NO_CHARGES = "No Charges"
ACCOUNTING_REVIEW_REQUIRED = "Posted - Review Required"

ACCOUNTING_STATUSES = (
    ACCOUNTING_NOT_ELIGIBLE,
    ACCOUNTING_PENDING,
    ACCOUNTING_POSTED,
    ACCOUNTING_NO_CHARGES,
    ACCOUNTING_REVIEW_REQUIRED,
)


def is_reconciliation_confirmed(match_status, resolution_status):
    """Accounting is allowed only after reconciliation has confirmed the bank transaction."""
    return cstr(match_status).strip() == "Matching" or cstr(resolution_status).strip() == "Manually Cleared"


def derive_accounting_status(confirmed, commission, vat, journal_entry_docstatus=None):
    """Pure status rule used by UI backfill and posting controls."""
    if cint(journal_entry_docstatus) == 1:
        return ACCOUNTING_POSTED if confirmed else ACCOUNTING_REVIEW_REQUIRED
    if not confirmed:
        return ACCOUNTING_NOT_ELIGIBLE
    if abs(flt(commission, 2)) <= 0.005 and abs(flt(vat, 2)) <= 0.005:
        return ACCOUNTING_NO_CHARGES
    return ACCOUNTING_PENDING


def accounting_group_key(row, consolidate_profiles):
    base = (
        cstr(row.settlement_number).strip(),
        cstr(row.settlement_date).strip(),
    )
    if consolidate_profiles:
        return base
    return (*base, cstr(row.pos_profile).strip())


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
            _("{0} {1} uses currency {2}. POS accounting v0.52.2 requires company-currency accounts ({3}).").format(
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
    bank_transactions = list(dict.fromkeys(cstr(value).strip() for value in bank_transactions or [] if cstr(value).strip()))
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
            confirmed = bool(latest and is_reconciliation_confirmed(latest.match_status, latest.resolution_status))
            status = derive_accounting_status(
                confirmed,
                bank.fee_amount,
                bank.vat_amount,
                journal_status.get(bank.journal_entry),
            )
            if bank.accounting_status != status:
                frappe.db.set_value(BANK_DOCTYPE, bank.name, "accounting_status", status, update_modified=False)
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


def _pending_rows_for_run(run_name, settlement_number=None, settlement_date=None, pos_profile=None):
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
        if latest_map.get(row.bank_transaction) and latest_map[row.bank_transaction].name == row.name
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
        if not is_reconciliation_confirmed(record.match_status, record.resolution_status):
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
        if settlement_number and row.settlement_number != cstr(settlement_number).strip():
            continue
        if settlement_date and row.settlement_date != getdate(settlement_date):
            continue
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
        "consolidate_pos_profiles": cint(settings.consolidate_pos_profiles_in_one_journal_entry),
        "pending_count": len(rows),
        "settlement_numbers": sorted({row.settlement_number for row in rows if row.settlement_number}),
        "settlement_dates": sorted({cstr(row.settlement_date) for row in rows if row.settlement_date}),
        "pos_profiles": sorted({row.pos_profile for row in rows if row.pos_profile}),
    }


def _prepare_groups(run_name, settlement_number, settlement_date=None, pos_profile=None):
    settings = get_accounting_settings(require_enabled=True)
    rows = _pending_rows_for_run(
        run_name,
        settlement_number=settlement_number,
        settlement_date=settlement_date,
        pos_profile=pos_profile,
    )
    if not rows:
        frappe.throw(_("No confirmed transactions are pending accounting for the selected filters."))

    if not cstr(settlement_number).strip():
        frappe.throw(_("Settlement Number is required for accounting posting."))

    dates = {row.settlement_date for row in rows if row.settlement_date}
    if any(not row.settlement_date for row in rows):
        frappe.throw(_("Settlement Date is required on every transaction before accounting posting."))
    if len(dates) > 1 and not settlement_date:
        frappe.throw(
            _("Settlement Number {0} has multiple settlement dates ({1}). Select Settlement Date before posting.").format(
                settlement_number,
                ", ".join(sorted(cstr(value) for value in dates)),
            )
        )

    for row in rows:
        if row.commission_amount < 0 or row.vat_amount < 0:
            frappe.throw(_("Negative commission/VAT is not supported in v0.52.2. Bank transaction: {0}").format(row.bank_transaction))

    _attach_cost_centers(rows, settings.company)
    consolidate = cint(settings.consolidate_pos_profiles_in_one_journal_entry)
    groups = defaultdict(list)
    for row in rows:
        groups[accounting_group_key(row, consolidate)].append(row)
    return settings, groups


def get_accounting_preview(run_name, settlement_number, settlement_date=None, pos_profile=None):
    _check_permission("read")
    settings, groups = _prepare_groups(run_name, settlement_number, settlement_date, pos_profile)
    rows = [row for group in groups.values() for row in group]
    return {
        "transaction_count": len(rows),
        "pos_profile_count": len({row.pos_profile for row in rows}),
        "journal_entry_count": len(groups),
        "commission": flt(sum(row.commission_amount for row in rows), 2),
        "vat": flt(sum(row.vat_amount for row in rows), 2),
        "total": flt(sum(row.commission_amount + row.vat_amount for row in rows), 2),
        "consolidate_pos_profiles": cint(settings.consolidate_pos_profiles_in_one_journal_entry),
    }


def create_accounting_postings(run_name, settlement_number, settlement_date=None, pos_profile=None):
    _check_permission("create")
    run = _check_run(run_name)
    settings, groups = _prepare_groups(run_name, settlement_number, settlement_date, pos_profile)

    created = []
    for _key, rows in groups.items():
        posting = frappe.new_doc(POSTING_DOCTYPE)
        posting.company = settings.company
        posting.source_run = run.name
        posting.settlement_number = rows[0].settlement_number
        posting.settlement_date = rows[0].settlement_date
        posting.posting_date = rows[0].settlement_date
        posting.consolidate_pos_profiles = cint(settings.consolidate_pos_profiles_in_one_journal_entry)
        posting.bank_account = settings.default_offset_account
        posting.commission_expense_account = settings.commission_expense_account
        posting.vat_input_account = settings.vat_input_account

        for row in rows:
            posting.append(
                "items",
                {
                    "reconciliation_record": row.name,
                    "bank_transaction": row.bank_transaction,
                    "transaction_date": row.transaction_date,
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
        created.append(
            {
                "posting": posting.name,
                "journal_entry": posting.journal_entry,
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
    }


def validate_posting_document(doc):
    if not doc.company or not doc.settlement_number or not doc.settlement_date or not doc.posting_date:
        frappe.throw(_("Company, Settlement Number, Settlement Date and Posting Date are required."))
    if not doc.items:
        frappe.throw(_("POS Accounting Posting requires at least one transaction."))

    settings = frappe._dict(
        company=doc.company,
        commission_expense_account=doc.commission_expense_account,
        vat_input_account=doc.vat_input_account,
        default_offset_account=doc.bank_account,
    )
    validate_accounting_settings(settings)

    seen = set()
    profiles = set()
    total_commission = 0.0
    total_vat = 0.0
    for item in doc.items:
        if not item.reconciliation_record or not item.bank_transaction:
            frappe.throw(_("Every posting item requires Reconciliation Record and Bank POS Transaction."))
        if item.bank_transaction in seen:
            frappe.throw(_("Bank transaction {0} appears more than once in the posting.").format(item.bank_transaction))
        seen.add(item.bank_transaction)
        if item.pos_profile:
            profiles.add(item.pos_profile)
        total_commission += flt(item.commission_amount, 2)
        total_vat += flt(item.vat_amount, 2)

    if not cint(doc.consolidate_pos_profiles) and len(profiles) > 1:
        frappe.throw(_("This posting is configured for one POS Profile only."))

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
            frappe.throw(_("POS Reconciliation Settings changed after this posting was prepared. Recreate the posting before submit."))
    if cint(doc.consolidate_pos_profiles) != cint(current_settings.consolidate_pos_profiles_in_one_journal_entry):
        frappe.throw(_("POS Profile consolidation setting changed. Recreate the posting before submit."))

    bank_names = [item.bank_transaction for item in doc.items]
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

    for item in doc.items:
        record = frappe.db.get_value(
            RECORD_DOCTYPE,
            item.reconciliation_record,
            ["name", "bank_transaction", "match_status", "resolution_status", "pos_profile"],
            as_dict=True,
        )
        bank = bank_map.get(item.bank_transaction)
        if not record or record.bank_transaction != item.bank_transaction or not bank:
            frappe.throw(_("Posting item {0} no longer matches its reconciliation source.").format(item.idx))
        latest = latest_map.get(item.bank_transaction)
        if not latest or latest.name != item.reconciliation_record:
            frappe.throw(
                _("Reconciliation record {0} is not the latest reconciliation result for bank transaction {1}.").format(
                    item.reconciliation_record, item.bank_transaction
                )
            )
        if not is_reconciliation_confirmed(record.match_status, record.resolution_status):
            frappe.throw(_("Bank transaction {0} is no longer confirmed by reconciliation.").format(item.bank_transaction))
        if bank.accounting_status != ACCOUNTING_PENDING:
            frappe.throw(
                _("Bank transaction {0} is not Pending Accounting (current status: {1}).").format(
                    item.bank_transaction, bank.accounting_status
                )
            )
        if cstr(bank.settlement_number).strip() != cstr(doc.settlement_number).strip() or getdate(bank.settlement_date) != getdate(doc.settlement_date):
            frappe.throw(_("Settlement details changed for bank transaction {0}. Refresh before posting.").format(item.bank_transaction))
        if abs(flt(bank.fee_amount, 2) - flt(item.commission_amount, 2)) > 0.005 or abs(flt(bank.vat_amount, 2) - flt(item.vat_amount, 2)) > 0.005:
            frappe.throw(_("Commission/VAT changed for bank transaction {0}. Refresh before posting.").format(item.bank_transaction))

        profile = bank.pos_profile or record.pos_profile
        cost_center = frappe.db.get_value("POS Profile", profile, "cost_center") if profile else None
        if not cost_center or cost_center != item.cost_center:
            frappe.throw(_("POS Profile cost center changed for {0}. Refresh before posting.").format(profile or item.bank_transaction))


def create_and_submit_journal_entry(posting_doc):
    validate_posting_before_submit(posting_doc)

    commission_by_cost_center = defaultdict(float)
    for item in posting_doc.items:
        commission_by_cost_center[item.cost_center] += flt(item.commission_amount, 2)

    je = frappe.new_doc("Journal Entry")
    je.voucher_type = "Bank Entry"
    je.company = posting_doc.company
    je.posting_date = posting_doc.posting_date
    je.cheque_no = posting_doc.settlement_number
    je.cheque_date = posting_doc.settlement_date
    je.user_remark = _("POS bank commission and VAT - Settlement {0} - {1}").format(
        posting_doc.settlement_number,
        posting_doc.settlement_date,
    )

    for cost_center, amount in sorted(commission_by_cost_center.items()):
        amount = flt(amount, 2)
        if amount:
            je.append(
                "accounts",
                {
                    "account": posting_doc.commission_expense_account,
                    "debit_in_account_currency": amount,
                    "exchange_rate": 1,
                    "cost_center": cost_center,
                    "user_remark": _("POS bank commission"),
                },
            )

    if flt(posting_doc.total_vat, 2):
        je.append(
            "accounts",
            {
                "account": posting_doc.vat_input_account,
                "debit_in_account_currency": flt(posting_doc.total_vat, 2),
                "exchange_rate": 1,
                "user_remark": _("VAT on POS bank commission"),
            },
        )

    if flt(posting_doc.total_commission, 2):
        je.append(
            "accounts",
            {
                "account": posting_doc.bank_account,
                "credit_in_account_currency": flt(posting_doc.total_commission, 2),
                "exchange_rate": 1,
                "user_remark": _("Bank charge - POS commission"),
            },
        )

    if flt(posting_doc.total_vat, 2):
        je.append(
            "accounts",
            {
                "account": posting_doc.bank_account,
                "credit_in_account_currency": flt(posting_doc.total_vat, 2),
                "exchange_rate": 1,
                "user_remark": _("Bank charge - VAT on POS commission"),
            },
        )

    if not je.accounts:
        frappe.throw(_("No commission or VAT amount is available for Journal Entry."))

    je.insert()
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


def on_journal_entry_cancel(doc, method=None):
    posting_name = frappe.db.get_value(POSTING_DOCTYPE, {"journal_entry": doc.name}, "name")
    if not posting_name:
        return
    frappe.db.set_value(POSTING_DOCTYPE, posting_name, "posting_status", "Journal Entry Cancelled", update_modified=False)
    release_posting(posting_name, doc.name)
