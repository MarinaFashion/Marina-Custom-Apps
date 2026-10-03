from datetime import datetime
from unittest import TestCase

from marina_custom_apps.pos_reconciliation.alhamrani_adapter import (
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
