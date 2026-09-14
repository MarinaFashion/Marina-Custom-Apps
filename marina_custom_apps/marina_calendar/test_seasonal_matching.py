import unittest
from marina_custom_apps.marina_calendar.seasonal_matching import (
    hijri_month_rows,
    matching_basis,
    seasonal_weight,
)


class SeasonalMatchingTests(unittest.TestCase):
    def test_basis_requires_manual_selection(self):
        for month in range(1, 13):
            self.assertIsNone(matching_basis(month))
        self.assertIsNone(matching_basis(9, 'Auto'))

    def test_manual_basis_options(self):
        self.assertEqual(matching_basis(9, 'Gregorian'), 'Gregorian')
        self.assertEqual(matching_basis(3, 'Hijri'), 'Hijri')
        self.assertIsNone(matching_basis(8, ''))
        self.assertIsNone(matching_basis(None))

    def test_same_day_preferred(self):
        for basis in ('Hijri', 'Gregorian'):
            self.assertGreater(seasonal_weight(basis, 9, 10, 9, 10), seasonal_weight(basis, 9, 10, 9, 20))
            self.assertEqual(seasonal_weight(basis, 9, 10, 8, 10), 1)

    def test_dhul_hijjah_whole_month_day_matching(self):
        for day in (1, 9, 10, 15, 20, 30):
            self.assertEqual(matching_basis(12, 'Hijri'), 'Hijri')
            self.assertGreater(seasonal_weight('Hijri', 12, day, 12, day),
                               seasonal_weight('Hijri', 12, day, 12, day - 1 or 2))
        self.assertGreater(seasonal_weight('Hijri', 12, 9, 12, 10), 1)
        self.assertGreater(seasonal_weight('Hijri', 12, 10, 12, 9), 1)

    def test_missing_historical_hijri(self):
        self.assertEqual(seasonal_weight('Hijri', 9, 10, None, None), 1)

    def test_hijri_primary_pool_excludes_other_months_and_invalid_days(self):
        rows = [
            {'id': 'ramadan', 'hijri_month': 9, 'hijri_day': 10},
            {'id': 'shaban', 'hijri_month': 8, 'hijri_day': 10},
            {'id': 'missing-day', 'hijri_month': 9, 'hijri_day': None},
        ]
        self.assertEqual([r['id'] for r in hijri_month_rows(rows, 9)], ['ramadan'])


if __name__ == '__main__':
    unittest.main()
