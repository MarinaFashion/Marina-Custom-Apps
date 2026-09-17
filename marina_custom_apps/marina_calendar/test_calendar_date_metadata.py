import json
import unittest
from pathlib import Path


class CalendarDateMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = (
            Path(__file__).resolve().parent
            / "doctype"
            / "marina_calendar_date"
            / "marina_calendar_date.json"
        )
        cls.definition = json.loads(path.read_text(encoding="utf-8"))

    def test_data_import_is_enabled(self):
        self.assertEqual(self.definition.get("allow_import"), 1)

    def test_date_field_does_not_use_unsupported_unique_flag(self):
        date_field = next(
            row for row in self.definition["fields"] if row["fieldname"] == "date"
        )
        self.assertFalse(date_field.get("unique"))


if __name__ == "__main__":
    unittest.main()
