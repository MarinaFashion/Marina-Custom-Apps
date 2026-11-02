"""Minimal basic shape tests; run using Python unittest without Frappe integration."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'marina_design_management' / 'doctype'

class TestStaticContract(unittest.TestCase):
    def test_unique_master_names(self):
        for folder in ('marina_fashion_category','marina_pantone','marina_mood_board'):
            schema=json.loads((ROOT/folder/(folder+'.json')).read_text())
            self.assertEqual(schema['doctype'],'DocType')
            self.assertTrue(schema['autoname'].startswith('field:'))

if __name__ == '__main__': unittest.main()
