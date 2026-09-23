from __future__ import annotations

import re
from collections.abc import Iterable

import frappe
from frappe import _
from frappe.utils import cint, cstr


SETTINGS_DOCTYPE = "Marina Accounting Settings"
ARABIC_FIELD = "custom_account_name_arabic"
_ARABIC_TEXT = re.compile(r"[\u0600-\u06ff]")
_MAX_CANDIDATES = 10000


def _standard_account_query(doctype, txt, searchfield, start, page_len, filters):
    """Call ERPNext's query directly so disabling this feature is a true fallback."""
    from erpnext.controllers.queries import get_account_list

    return get_account_list(doctype, txt, searchfield, start, page_len, filters)


def _is_enabled() -> bool:
    if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
        return False
    return bool(
        cint(
            frappe.db.get_single_value(
                SETTINGS_DOCTYPE,
                "enable_bilingual_account_search",
                cache=True,
            )
        )
    )


def _has_arabic_field() -> bool:
    return bool(frappe.get_meta("Account").has_field(ARABIC_FIELD))


def _rows_by_name(names: Iterable[str]):
    names = list(dict.fromkeys(name for name in names if name))
    if not names:
        return {}

    rows = frappe.get_all(
        "Account",
        filters={"name": ["in", names]},
        fields=["name", "account_name", "account_number", ARABIC_FIELD],
        limit_page_length=0,
    )
    return {row.name: row for row in rows}


def _is_arabic_language() -> bool:
    return cstr(getattr(frappe.local, "lang", "")).lower().startswith("ar")


def _format_rows(rows):
    records = _rows_by_name(row[0] for row in rows)
    arabic_first = _is_arabic_language()
    formatted = []

    for result in rows:
        name = result[0]
        account = records.get(name)
        if not account:
            formatted.append(result)
            continue

        english = cstr(account.account_name).strip()
        arabic = cstr(account.get(ARABIC_FIELD)).strip()
        number = cstr(account.account_number).strip()
        primary = arabic if arabic_first and arabic else english or name
        secondary = english if primary == arabic else arabic

        # When Account uses show_title_field_in_link, the second value becomes
        # the visible label. Otherwise these values remain useful descriptions.
        formatted.append((name, primary, number, secondary))

    return formatted


def _matches(account, text: str) -> bool:
    needle = text.casefold()
    values = (
        account.name,
        account.account_name,
        account.account_number,
        account.get(ARABIC_FIELD),
    )
    return any(needle in cstr(value).casefold() for value in values if value)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def bilingual_account_query(
    doctype,
    txt,
    searchfield,
    start,
    page_len,
    filters,
    **kwargs,
):
    """Return ERPNext-filtered Account choices with Arabic and English labels.

    ERPNext's own account query remains the source of candidate records, so
    company, ledger/group, disabled and permission filters continue to apply.
    Arabic searches request a larger filtered candidate set, then match the
    Marina Arabic-name field in Python. No Account is renamed or rewritten.
    """
    if not _is_enabled() or not _has_arabic_field():
        return _standard_account_query(
            doctype, txt, searchfield, start, page_len, filters
        )

    text = cstr(txt).strip()
    start = max(cint(start), 0)
    page_len = max(cint(page_len), 1)

    if not text or not _ARABIC_TEXT.search(text):
        rows = _standard_account_query(
            doctype, text, searchfield, start, page_len, filters
        )
        return _format_rows(rows)

    candidates = _standard_account_query(
        doctype,
        "",
        searchfield,
        0,
        _MAX_CANDIDATES,
        filters,
    )
    records = _rows_by_name(row[0] for row in candidates)
    matches = [
        row for row in candidates
        if records.get(row[0]) and _matches(records[row[0]], text)
    ]
    matches.sort(
        key=lambda row: (
            not cstr(records[row[0]].get(ARABIC_FIELD)).casefold().startswith(
                text.casefold()
            ),
            cstr(records[row[0]].get(ARABIC_FIELD)).casefold(),
            row[0],
        )
    )
    return _format_rows(matches[start : start + page_len])


@frappe.whitelist()
def get_feature_status():
    """Small diagnostic endpoint for Demo verification."""
    frappe.only_for(("System Manager", "Accounts Manager"))
    return {
        "enabled": _is_enabled(),
        "arabic_field": ARABIC_FIELD,
        "message": _("Bilingual account search is enabled")
        if _is_enabled()
        else _("Bilingual account search is disabled"),
    }
