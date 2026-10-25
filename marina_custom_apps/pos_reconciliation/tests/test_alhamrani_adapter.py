from datetime import datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from marina_custom_apps.pos_reconciliation.alhamrani_adapter import (
    AlhamraniAdapter,
    _parse_date,
    _parse_time,
)


class TestAlhamraniAdapterParsing(TestCase):
    def test_terminal_mmdd_uses_anchor_year(self):
        self.assertEqual(
            str(_parse_date("0930", datetime(2026, 9, 30, 22, 0, 0))),
            "2026-09-30",
        )

    def test_terminal_mmdd_handles_year_boundary(self):
        self.assertEqual(
            str(_parse_date("1231", datetime(2027, 1, 1, 0, 2, 0))),
            "2026-12-31",
        )

    def test_terminal_hhmmss(self):
        self.assertEqual(_parse_time("224904"), "22:49:04")


class TestAlhamraniSourceLoading(TestCase):
    def _adapter(self, responded_at="responded_at", sent_at="sent_at"):
        # Exercise get_rows without requiring a configured source DocType.
        adapter = AlhamraniAdapter.__new__(AlhamraniAdapter)
        adapter.meta = SimpleNamespace(has_field=lambda field: False)
        adapter.fields = {"responded_at": responded_at, "sent_at": sent_at}
        return adapter

    def test_manual_slip_uses_creation_when_response_timestamps_missing(self):
        adapter = self._adapter()
        calls = []

        def fake_get_all(doctype, **kwargs):
            calls.append(kwargs)
            if kwargs["order_by"] == "creation asc":
                return [{"name": "Demo-AUP-MANUAL", "creation": "2026-10-21 12:00:00"}]
            return []

        with patch("marina_custom_apps.pos_reconciliation.alhamrani_adapter.frappe.get_all",
                   side_effect=fake_get_all):
            rows = adapter.get_rows("2026-10-20", "2026-10-25")

        self.assertEqual([row["name"] for row in rows], ["Demo-AUP-MANUAL"])
        self.assertEqual(len(calls), 3)
        fallback = calls[2]["filters"]
        self.assertEqual(fallback["responded_at"], ["is", "not set"])
        self.assertEqual(fallback["sent_at"], ["is", "not set"])
        self.assertEqual(
            fallback["creation"],
            ["between", ["2026-10-19 00:00:00", "2026-10-26 23:59:59"]],
        )

    def test_sent_timestamp_is_used_only_when_response_timestamp_missing(self):
        adapter = self._adapter()
        filters_by_field = {}

        def fake_get_all(doctype, **kwargs):
            field = kwargs["order_by"].split()[0]
            filters_by_field[field] = kwargs["filters"]
            return [{"name": field}]

        with patch("marina_custom_apps.pos_reconciliation.alhamrani_adapter.frappe.get_all",
                   side_effect=fake_get_all):
            rows = adapter.get_rows("2026-10-20", "2026-10-25")

        self.assertEqual([r["name"] for r in rows], ["responded_at", "sent_at", "creation"])
        self.assertNotIn("sent_at", filters_by_field["responded_at"])
        self.assertEqual(filters_by_field["sent_at"]["responded_at"], ["is", "not set"])
        self.assertEqual(filters_by_field["creation"]["sent_at"], ["is", "not set"])

    def test_creation_fallback_when_no_terminal_timestamps_in_schema(self):
        adapter = self._adapter(responded_at=None, sent_at=None)
        with patch("marina_custom_apps.pos_reconciliation.alhamrani_adapter.frappe.get_all",
                   return_value=[{"name": "Demo-AUP-MANUAL"}]) as mocked:
            result = adapter.get_rows("2026-10-20", "2026-10-25")
        self.assertEqual(len(result), 1)
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(mocked.call_args.kwargs["order_by"], "creation asc")
