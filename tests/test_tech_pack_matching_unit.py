"""Pure matching invariants, with no Frappe site required."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path


class Row(dict):
    def __getattr__(self, key):
        return self.get(key)


class TechPackMatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = {key: sys.modules.get(key) for key in ("frappe", "frappe.utils")}
        frappe = types.ModuleType("frappe")
        utils = types.ModuleType("frappe.utils")
        utils.now_datetime = lambda: "2026-11-09 00:00:00"
        utils.cint = lambda v: int(v or 0)
        frappe.utils = utils
        frappe._dict = Row
        sys.modules["frappe"] = frappe
        sys.modules["frappe.utils"] = utils
        path = (Path(__file__).resolve().parents[1] /
                "marina_custom_apps/design_management/clean_milestones/tech_pack_matching.py")
        spec = importlib.util.spec_from_file_location("_marina_tech_pack_test", path)
        cls.match = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.match)
        cls.frappe = frappe

    @classmethod
    def tearDownClass(cls):
        for key, original in cls.saved.items():
            if original is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = original

    def setUp(self):
        self.design = Row(
            mood_board="MB-S27-SOFT-TAILORING",
            designer="razan@example.test",
            tech_pack_not_required=0,
        )
        self.doc = Row(
            document_type="Tech Pack",
            tech_pack_mood_board="MB-S27-SOFT-TAILORING",
            publication_status="Published",
            superseded_by=None,
            additional_files=[
                Row(designer="razan@example.test", file="/private/files/razan.pdf"),
                Row(designer="khadega@example.test", file="/private/files/khadega.pdf"),
            ],
        )

    def test_correct_designer_receives_only_own_file(self):
        self.assertEqual(self.match.designer_file(self.doc, self.design),
                         "/private/files/razan.pdf")
        self.design.designer = "khadega@example.test"
        self.assertEqual(self.match.designer_file(self.doc, self.design),
                         "/private/files/khadega.pdf")

    def test_mood_board_or_designer_mismatch_refuses_file(self):
        self.design.mood_board = "OTHER-BOARD"
        self.assertIsNone(self.match.designer_file(self.doc, self.design))
        self.design.mood_board = self.doc.tech_pack_mood_board
        self.design.designer = "other@example.test"
        self.assertIsNone(self.match.designer_file(self.doc, self.design))

    def test_draft_superseded_or_non_tech_pack_never_matches(self):
        for key, value in (
            ("publication_status", "Draft"),
            ("superseded_by", "DDOC-OLDER"),
            ("document_type", "Fitting Report"),
        ):
            original = self.doc[key]
            self.doc[key] = value
            self.assertIsNone(self.match.designer_file(self.doc, self.design))
            self.doc[key] = original

    def test_waiver_and_duplicate_designer_files_never_auto_match(self):
        self.design.tech_pack_not_required = "1"
        self.assertIsNone(self.match.designer_file(self.doc, self.design))
        self.design.tech_pack_not_required = "0"
        self.doc.additional_files.append(
            Row(designer="razan@example.test", file="/private/files/other.pdf"))
        self.assertIsNone(self.match.designer_file(self.doc, self.design))


if __name__ == "__main__":
    unittest.main()
