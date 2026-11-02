"""Native multipart chat attachment validation tests for Frappe v15 demo."""
from unittest import TestCase
from unittest.mock import patch

import frappe

from marina_custom_apps.design_management.discussions import (
    _create_discussion_message,
    validate_binary_attachment,
)


class TestNativeDiscussionUpload(TestCase):
    def test_regular_and_design_attachment_types(self):
        for filename in ("sample.pdf", "tech-pack.zip", "artwork.psd",
                         "factory-video.mp4", "presentation.pptx"):
            name, raw, is_image = validate_binary_attachment(filename, b"example")
            self.assertEqual(name, filename)
            self.assertEqual(raw, b"example")
            self.assertFalse(is_image)

    def test_invalid_types_and_large_payload_are_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            validate_binary_attachment("execute.exe", b"example")
        with self.assertRaises(frappe.ValidationError):
            validate_binary_attachment("techpack.zip", b"x" * 1024, max_size=100)

    def test_parent_access_is_checked_before_database_insert(self):
        with patch("marina_custom_apps.design_management.discussions.parent_access",
                   side_effect=frappe.PermissionError):
            with patch("marina_custom_apps.design_management.discussions.frappe.db.exists") as exists:
                with self.assertRaises(frappe.PermissionError):
                    _create_discussion_message(
                        "Design Code", "UNAUTHORIZED", "hello", None,
                        "a" * 32, "[]", attachment=None
                    )
                exists.assert_not_called()
