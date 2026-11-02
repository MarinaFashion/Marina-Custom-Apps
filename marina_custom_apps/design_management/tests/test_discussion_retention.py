"""Policy boundary checks; run with bench --site demo run-tests --app marina_custom_apps.design_management."""
from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import patch

import frappe

from marina_custom_apps.design_management.discussion_retention import (
    THRESHOLD_BYTES,
    RETENTION_DAYS,
    expiry_for_size,
    is_past_expiry,
    expire_large_attachments,
    get_retention_policy,
    MIB,
)


class TestDiscussionRetention(TestCase):
    def test_fifty_mib_or_less_never_expires(self):
        uploaded = datetime(2026, 11, 1, 10, 0)
        policy = {"threshold_bytes": THRESHOLD_BYTES, "retention_days": RETENTION_DAYS}
        self.assertIsNone(expiry_for_size(0, uploaded, policy))
        self.assertIsNone(expiry_for_size(THRESHOLD_BYTES - 1, uploaded, policy))
        self.assertIsNone(expiry_for_size(THRESHOLD_BYTES, uploaded, policy))

    def test_files_over_fifty_mib_expire_after_fourteen_days(self):
        uploaded = datetime(2026, 11, 1, 10, 0)
        policy = {"threshold_bytes": THRESHOLD_BYTES, "retention_days": RETENTION_DAYS}
        expiry = expiry_for_size(THRESHOLD_BYTES + 1, uploaded, policy)
        self.assertEqual(expiry, uploaded + timedelta(days=RETENTION_DAYS))
        self.assertFalse(is_past_expiry({"attachment_expires_on": expiry, "attachment_expired": 0},
                                        uploaded + timedelta(days=13)))
        self.assertTrue(is_past_expiry({"attachment_expires_on": expiry, "attachment_expired": 0},
                                       uploaded + timedelta(days=14)))

    def test_changed_policy_only_applies_to_future_uploads(self):
        uploaded = datetime(2026, 11, 1, 10, 0)
        old = {"threshold_bytes": 50 * MIB, "retention_days": 14}
        new = {"threshold_bytes": 20 * MIB, "retention_days": 7}
        size = 30 * MIB
        self.assertIsNone(expiry_for_size(size, uploaded, old))
        self.assertEqual(expiry_for_size(size, uploaded, new), uploaded + timedelta(days=7))
        previously_assigned = expiry_for_size(70 * MIB, uploaded, old)
        self.assertEqual(previously_assigned, uploaded + timedelta(days=14))
        # Once assigned, that expiry is not derived from current configuration.
        self.assertFalse(is_past_expiry({"attachment_expires_on": previously_assigned, "attachment_expired": 0}, uploaded + timedelta(days=8)))

    def test_retention_policy_reads_settings_and_uses_default_for_unset(self):
        scope = "marina_custom_apps.design_management.discussion_retention.frappe.db.get_single_value"
        settings = {
            "discussion_retention_threshold_mb": 25,
            "discussion_retention_days": 5,
        }
        with patch(scope, side_effect=lambda dt, field: settings[field]):
            self.assertEqual(get_retention_policy(), {
                "threshold_mb": 25, "threshold_bytes": 25 * MIB, "retention_days": 5
            })
        with patch(scope, return_value=None):
            self.assertEqual(get_retention_policy()["retention_days"], RETENTION_DAYS)
            self.assertEqual(get_retention_policy()["threshold_bytes"], THRESHOLD_BYTES)

    def test_invalid_retention_policy_is_rejected(self):
        scope = "marina_custom_apps.design_management.discussion_retention.frappe.db.get_single_value"
        for threshold in (0, -1, 501):
            with patch(scope, side_effect=lambda doctype, field: threshold if field == "discussion_retention_threshold_mb" else 14):
                with self.assertRaises(frappe.ValidationError):
                    get_retention_policy()

    def test_expired_marker_remains_effective(self):
        self.assertTrue(is_past_expiry({"attachment_expires_on": None, "attachment_expired": 1}))
        self.assertFalse(is_past_expiry({"attachment_expires_on": None, "attachment_expired": 0}))

    def test_cleanup_clears_file_link_before_deletion(self):
        expired_at = datetime(2026, 11, 1, 10, 0)
        current_time = datetime(2026, 11, 1, 11, 0)
        msg = frappe._dict(
            name="discussion-test",
            # Lower than the original 50 MB default: cleanup relies on the
            # stored expiry timestamp, not today's editable size threshold.
            attachment_size=20 * MIB,
            attachment_file_id="file-test",
            attachment_url="/private/files/test.pdf",
            attachment_expires_on=expired_at,
            attachment_expired=0,
        )
        file = frappe._dict(
            name="file-test", file_url=msg.attachment_url,
            file_size=msg.attachment_size, is_private=1,
            attached_to_doctype="Marina Discussion Message",
            attached_to_name=msg.name,
        )
        operations = []

        def set_value(doctype, name, fields, **kwargs):
            operations.append(("unlink", doctype, name, fields))

        def delete_doc(doctype, name, **kwargs):
            operations.append(("delete", doctype, name, kwargs))

        scope = "marina_custom_apps.design_management.discussion_retention"
        with (
            patch(scope + ".now_datetime", return_value=current_time),
            patch(scope + ".frappe.get_all", return_value=[frappe._dict(name=msg.name)]),
            patch(scope + ".frappe.db.savepoint"),
            patch(scope + ".frappe.db.sql"),
            patch(scope + ".frappe.get_doc", return_value=msg),
            patch(scope + ".frappe.db.get_value", return_value=file),
            patch(scope + ".frappe.db.set_value", side_effect=set_value),
            patch(scope + ".frappe.delete_doc", side_effect=delete_doc),
        ):
            self.assertEqual(expire_large_attachments(), 1)

        self.assertEqual([op[0] for op in operations], ["unlink", "delete"])
        self.assertIsNone(operations[0][3]["attachment_file_id"])
        self.assertEqual(operations[0][3]["attachment_expired"], 1)
        self.assertEqual(operations[0][3]["attachment_url"], "")
        self.assertEqual(operations[1][3], {"ignore_permissions": True})
        self.assertNotIn("ignore_links", operations[1][3])

    def test_failed_file_deletion_rolls_back_the_unlink(self):
        expired_at = datetime(2026, 11, 1, 10, 0)
        msg = frappe._dict(
            name="discussion-test",
            attachment_size=THRESHOLD_BYTES + 100,
            attachment_file_id="file-test",
            attachment_url="/private/files/test.pdf",
            attachment_expires_on=expired_at,
            attachment_expired=0,
        )
        file = frappe._dict(
            name="file-test", file_url=msg.attachment_url,
            file_size=msg.attachment_size, is_private=1,
            attached_to_doctype="Marina Discussion Message",
            attached_to_name=msg.name,
        )
        scope = "marina_custom_apps.design_management.discussion_retention"
        with (
            patch(scope + ".now_datetime", return_value=datetime(2026, 11, 1, 11, 0)),
            patch(scope + ".frappe.get_all", return_value=[frappe._dict(name=msg.name)]),
            patch(scope + ".frappe.db.savepoint"),
            patch(scope + ".frappe.db.sql"),
            patch(scope + ".frappe.get_doc", return_value=msg),
            patch(scope + ".frappe.db.get_value", return_value=file),
            patch(scope + ".frappe.db.set_value") as set_value,
            patch(scope + ".frappe.delete_doc", side_effect=RuntimeError("test failure")),
            patch(scope + ".frappe.db.rollback") as rollback,
            patch(scope + ".frappe.log_error"),
            patch(scope + ".frappe.get_traceback", return_value="test failure"),
        ):
            self.assertEqual(expire_large_attachments(), 0)
            set_value.assert_called_once()
            rollback.assert_called_once_with(save_point="mdm_large_attachment_expiry")
