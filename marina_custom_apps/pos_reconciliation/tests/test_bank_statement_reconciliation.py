from __future__ import annotations

import unittest

from marina_custom_apps.pos_reconciliation.bank_statement_reconciliation_service import (
    normalize_settlement_number,
    normalize_statement_card_type,
    parse_pos_statement_text,
    parse_statement_reconciliation_date,
    terminal_bank_reference,
)


class TestPOSBankStatementParser(unittest.TestCase):
    def setUp(self):
        self.mappings = [
            ("SM", "MADA", "Gross"),
            ("FS", "MADA", "Commission"),
            ("VS", "MADA", "VAT"),
            ("VC", "VISA", "Gross"),
            ("FV", "VISA", "Commission"),
            ("VV", "VISA", "VAT"),
        ]

    def test_normalize_settlement_number(self):
        self.assertEqual(normalize_settlement_number("000263"), "263")
        self.assertEqual(normalize_settlement_number("263"), "263")

    def test_terminal_reference_uses_leading_eight_digits(self):
        self.assertEqual(terminal_bank_reference("5562102342112671", 8), "55621023")


    def test_parse_statement_reconciliation_date(self):
        self.assertEqual(
            str(parse_statement_reconciliation_date("260929")),
            "2026-09-29",
        )

    def test_unified_card_type_aliases(self):
        self.assertEqual(normalize_statement_card_type("GCC CARD"), "GCCCARD")
        self.assertEqual(normalize_statement_card_type("AMERICAN EXPRESS"), "AMEX")

    def test_parse_mada_gross(self):
        parsed = parse_pos_statement_text(
            "RECON NO: 000263 000000 REFERENCE: 55621023 SM260925",
            mappings=self.mappings,
        )
        self.assertEqual(parsed.settlement_number, "263")
        self.assertEqual(parsed.bank_terminal_reference, "55621023")
        self.assertEqual(parsed.card_type, "MADA")
        self.assertEqual(parsed.component, "Gross")
        self.assertEqual(str(parsed.reconciliation_date), "2026-09-25")

    def test_parse_visa_vat(self):
        parsed = parse_pos_statement_text(
            "RECON NO: 000263 000000 REFERENCE: 55621023 VV260925",
            mappings=self.mappings,
        )
        self.assertEqual(parsed.card_type, "VISA")
        self.assertEqual(parsed.component, "VAT")

    def test_non_pos_line_is_not_classified(self):
        self.assertIsNone(
            parse_pos_statement_text(
                "Supplier transfer payment invoice 100234",
                mappings=self.mappings,
            )
        )
