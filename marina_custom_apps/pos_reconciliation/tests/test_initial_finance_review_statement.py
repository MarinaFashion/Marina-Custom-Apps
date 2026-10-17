"""Regressions for initial imported Finance reviews during POS statement matching."""

from datetime import datetime
from unittest import TestCase
from unittest.mock import patch

import frappe

from marina_custom_apps.pos_reconciliation.unified_statement_reconciliation import (
    _has_protected_statement_change,
    _update_records,
)


def _record(**overrides):
    values = dict(
        name="PREC-TEST",
        bank_transaction="BPT-TEST",
        match_status="Bank Only - Not Settled",
        resolution_status="Manually Cleared",
        bank_statement_status="Not Checked",
        finance_review_status="Checked & Approved",
        accounting_status="Not Eligible",
        accounting_posting=None,
        journal_entry=None,
    )
    values.update(overrides)
    return frappe._dict(values)


def _new_evidence():
    return {
        "match_status": "Bank Only - Settled",
        "resolution_status": "Manually Cleared",
        "bank_statement_status": "Fully Reconciled",
    }


class TestInitialFinanceApprovalStatementHandling(TestCase):
    def test_newly_created_with_inherited_approval_is_not_historical_review(self):
        self.assertFalse(
            _has_protected_statement_change(
                _record(), _new_evidence(), {"PREC-TEST"}
            )
        )

    def test_existing_approved_record_rejects_actual_bank_status_change(self):
        self.assertTrue(
            _has_protected_statement_change(
                _record(), _new_evidence(), set()
            )
        )

    def test_newly_created_investigation_still_blocks_change(self):
        self.assertTrue(
            _has_protected_statement_change(
                _record(finance_review_status="Needs Investigation",
                        resolution_status="Pending"),
                _new_evidence(),
                {"PREC-TEST"},
            )
        )

    def test_new_record_with_draft_accounting_still_blocks_change(self):
        self.assertTrue(
            _has_protected_statement_change(
                _record(accounting_status="Draft Created"), _new_evidence(),
                {"PREC-TEST"}
            )
        )

    def test_new_record_with_posted_journal_still_blocks_change(self):
        self.assertTrue(
            _has_protected_statement_change(
                _record(accounting_status="Posted", journal_entry="JE-0001"),
                _new_evidence(), {"PREC-TEST"}
            )
        )

    def test_identical_protected_outcome_is_allowed(self):
        r = _record()
        self.assertFalse(
            _has_protected_statement_change(
                r, {
                    "match_status": r.match_status,
                    "resolution_status": r.resolution_status,
                    "bank_statement_status": r.bank_statement_status,
                },
                set(),
            )
        )

    @patch("marina_custom_apps.pos_reconciliation.unified_statement_reconciliation.frappe.db.set_value")
    def test_new_approved_record_reconciles_and_keeps_manual_decision(self, setter):
        record = _record()
        key = ("526", "12345678", "2026-09-29", "MADA")
        settlement = frappe._dict(name="SET-1", status="Fully Reconciled")
        rows = [frappe._dict(name="MBST-1")]
        _update_records(
            frappe._dict(name="POS Reconciliation Run"), [record],
            {record.name: key}, {key: settlement}, {key: rows},
            datetime(2026, 10, 18), newly_created_names={record.name},
        )
        setter.assert_called_once()
        saved = setter.call_args.args[2]
        self.assertEqual(saved["match_status"], "Bank Only - Settled")
        self.assertEqual(saved["resolution_status"], "Manually Cleared")
        self.assertEqual(saved["bank_statement_status"], "Fully Reconciled")

    @patch("marina_custom_apps.pos_reconciliation.unified_statement_reconciliation.frappe.db.set_value")
    def test_existing_manual_clearance_not_rejected_for_only_resolution(self, setter):
        record = _record(bank_statement_status="Fully Reconciled",
                         match_status="Bank Only - Settled")
        key = ("526", "12345678", "2026-09-29", "MADA")
        _update_records(
            frappe._dict(name="POS Reconciliation Run"), [record],
            {record.name: key},
            {key: frappe._dict(name="SET-1", status="Fully Reconciled")},
            {key: [frappe._dict(name="MBST-1")]},
            datetime(2026, 10, 18), newly_created_names=set(),
        )
        saved = setter.call_args.args[2]
        self.assertEqual(saved["resolution_status"], "Manually Cleared")
        self.assertEqual(saved["bank_statement_status"], "Fully Reconciled")
