import unittest

import frappe

from marina_custom_apps.stock_transfer_control.api import (
    _matches_warehouse,
    _warehouse_link_row,
)


class TestBilingualWarehouseSearch(unittest.TestCase):
    def setUp(self):
        self.warehouse = frappe._dict(
            name="Jeddah Store - MA",
            custom_warehouse_name_arabic="معرض جدة",
        )

    def test_matches_standard_warehouse_name(self):
        self.assertTrue(_matches_warehouse(self.warehouse, "Jeddah"))

    def test_matches_arabic_warehouse_name(self):
        self.assertTrue(_matches_warehouse(self.warehouse, "جدة"))

    def test_rejects_unmatched_text(self):
        self.assertFalse(_matches_warehouse(self.warehouse, "Riyadh"))

    def test_link_result_includes_arabic_name(self):
        self.assertEqual(
            _warehouse_link_row(self.warehouse),
            ["Jeddah Store - MA", "معرض جدة"],
        )


if __name__ == "__main__":
    unittest.main()
