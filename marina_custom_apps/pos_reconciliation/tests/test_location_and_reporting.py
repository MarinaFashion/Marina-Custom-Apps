from datetime import date
from unittest import TestCase

from marina_custom_apps.pos_reconciliation.location_service import select_pos_profile
from marina_custom_apps.pos_reconciliation.reporting import commission_pct, display_card_type, raw_card_type


class TestTerminalLocationResolution(TestCase):
    def test_effective_date_resolves_historical_pos_profile(self):
        periods = [
            {"pos_profile": "Andalus Mall", "from_date": date(2026, 1, 1), "to_date": date(2026, 9, 15)},
            {"pos_profile": "Yanbu", "from_date": date(2026, 9, 16), "to_date": None},
        ]
        self.assertEqual(select_pos_profile(periods, date(2026, 9, 15)), "Andalus Mall")
        self.assertEqual(select_pos_profile(periods, date(2026, 9, 16)), "Yanbu")
        self.assertIsNone(select_pos_profile(periods, date(2025, 12, 31)))


class TestPOSCommissionReporting(TestCase):
    def test_weighted_commission_percentage(self):
        self.assertAlmostEqual(commission_pct(15, 1000), 1.5)

    def test_card_type_display_and_filter_mapping(self):
        self.assertEqual(display_card_type("SPAN"), "Mada")
        self.assertEqual(display_card_type("MASTER_CARD"), "Mastercard")
        self.assertEqual(raw_card_type("Mada"), "SPAN")
        self.assertEqual(raw_card_type("Mastercard"), "MASTER_CARD")
