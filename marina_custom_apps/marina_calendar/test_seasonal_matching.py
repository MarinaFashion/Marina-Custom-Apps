import unittest
from marina_custom_apps.marina_calendar.seasonal_matching import matching_basis, seasonal_weight


class SeasonalMatchingTests(unittest.TestCase):
    def test_auto_all_months(self):
        for month in range(1, 13):
            self.assertEqual(matching_basis(month), 'Hijri' if month in (8, 9, 11, 12) else 'Gregorian')

    def test_overrides_and_existing_blank_rows(self):
        self.assertEqual(matching_basis(9, 'Gregorian'), 'Gregorian')
        self.assertEqual(matching_basis(3, 'Hijri'), 'Hijri')
        self.assertEqual(matching_basis(8, ''), 'Hijri')
        self.assertEqual(matching_basis(None), 'Gregorian')

    def test_same_day_preferred(self):
        for basis in ('Hijri', 'Gregorian'):
            self.assertGreater(seasonal_weight(basis, 9, 10, 9, 10), seasonal_weight(basis, 9, 10, 9, 20))
            self.assertEqual(seasonal_weight(basis, 9, 10, 8, 10), 1)

    def test_dhul_hijjah_whole_month_day_matching(self):
        for day in (1, 9, 10, 15, 20, 30):
            self.assertEqual(matching_basis(12), 'Hijri')
            self.assertGreater(seasonal_weight('Hijri', 12, day, 12, day),
                               seasonal_weight('Hijri', 12, day, 12, day - 1 or 2))
        self.assertGreater(seasonal_weight('Hijri', 12, 9, 12, 10), 1)
        self.assertGreater(seasonal_weight('Hijri', 12, 10, 12, 9), 1)

    def test_missing_historical_hijri(self):
        self.assertEqual(seasonal_weight('Hijri', 9, 10, None, None), 1)


if __name__ == '__main__':
    unittest.main()
