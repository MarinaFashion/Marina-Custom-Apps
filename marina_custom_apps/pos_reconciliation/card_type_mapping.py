from __future__ import annotations

from collections import defaultdict

import frappe
from frappe.utils import cstr

SETTINGS_DOCTYPE = "POS Reconciliation Settings"


def normalize_card_type_token(value) -> str:
    """Technical normalization only. Business aliases are stored in Settings."""
    text = cstr(value).strip().upper().replace("_", " ").replace("-", " ")
    return " ".join(text.split())


class CardTypeMapper:
    def __init__(self, rows=None):
        self.bank_aliases = {}
        self.alhamrani_aliases = {}
        self._bank_raw_by_unified = defaultdict(set)
        for row in rows or []:
            get = row.get if hasattr(row, "get") else lambda key: getattr(row, key, None)
            unified = normalize_card_type_token(get("unified_card_type"))
            bank_raw = get("bank_card_type")
            alh_raw = get("alhamrani_card_type")
            bank = normalize_card_type_token(bank_raw)
            alh = normalize_card_type_token(alh_raw)
            if not unified:
                continue
            if bank:
                self.bank_aliases[bank] = unified
                self._bank_raw_by_unified[unified].add(cstr(bank_raw).strip().upper())
            if alh:
                self.alhamrani_aliases[alh] = unified

    def bank(self, value) -> str:
        token = normalize_card_type_token(value)
        return self.bank_aliases.get(token, token)

    def alhamrani(self, value) -> str:
        token = normalize_card_type_token(value)
        return self.alhamrani_aliases.get(token, token)

    def resolve(self, value) -> str:
        token = normalize_card_type_token(value)
        return self.bank_aliases.get(token) or self.alhamrani_aliases.get(token) or token

    def bank_source_values(self, unified_value):
        unified = self.resolve(unified_value)
        values = set(self._bank_raw_by_unified.get(unified, set()))
        if unified:
            values.add(unified)
        return tuple(sorted(values))


def get_card_type_mapper():
    settings = frappe.get_single(SETTINGS_DOCTYPE)
    return CardTypeMapper(settings.get("card_type_mappings") or [])