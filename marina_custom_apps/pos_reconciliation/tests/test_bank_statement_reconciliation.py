from __future__ import annotations

import unittest

from marina_custom_apps.pos_reconciliation.bank_statement_reconciliation_service import (
    normalize_settlement_number,
    parse_pos_statement_text,
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

    def test_parse_mada_gross(self):
        parsed = parse_pos_statement_text(
            "RECON NO: 000263 000000 REFERENCE: 55621023 SM260925",
            mappings=self.mappings,
        )
        self.assertEqual(parsed.settlement_number, "263")
        self.assertEqual(parsed.bank_terminal_reference, "55621023")
        self.assertEqual(parsed.card_type, "MADA")
        self.assertEqual(parsed.component, "Gross")

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
