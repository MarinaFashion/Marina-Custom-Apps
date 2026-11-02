"""Retention of large, message-owned discussion attachments only.

No non-discussion File or Design Document evidence is eligible. The expiry
date is set once when a file is attached; editing/replying cannot extend it.
The scheduled cleanup is conservative and idempotent.
"""
from datetime import timedelta

import frappe
from frappe.utils import now_datetime, get_datetime

MESSAGE = "Marina Discussion Message"
SETTINGS = "Design Management Settings"
# Defaults are preserved for existing deployments and new installations.
# Stored attachment_expires_on is the immutable authority for old uploads.
THRESHOLD_BYTES = 50 * 1024 * 1024
RETENTION_DAYS = 14
MIB = 1024 * 1024


def get_retention_policy():
    """Read two cached Single DocType fields without loading its role tables."""
    limit = frappe.db.get_single_value(SETTINGS, "discussion_retention_threshold_mb")
    days = frappe.db.get_single_value(SETTINGS, "discussion_retention_days")
    try:
        limit = int(limit) if limit is not None and str(limit) != "" else 50
        days = int(days) if days is not None and str(days) != "" else RETENTION_DAYS
    except (ValueError, TypeError):
        # Invalid settings must be corrected by an administrator; do not
        # silently create files with unpredictable expiry dates.
        frappe.throw("Invalid discussion attachment retention settings.")
    if not (1 <= limit <= 500 and 1 <= days <= 365):
        frappe.throw("Invalid discussion attachment retention settings.")
    return {
        "threshold_mb": limit,
        "threshold_bytes": limit * MIB,
        "retention_days": days,
    }


def expiry_for_size(size, uploaded_at=None, policy=None):
    """Assign an expiry once, at upload, under the then-current settings."""
    policy = policy if policy is not None else get_retention_policy()
    if int(size or 0) <= int(policy["threshold_bytes"]):
        return None
    return get_datetime(uploaded_at or now_datetime()) + timedelta(days=int(policy["retention_days"]))


def is_past_expiry(message, now=None):
    expiry = message.get("attachment_expires_on")
    return bool(
        message.get("attachment_expired")
        or (expiry and get_datetime(expiry) <= get_datetime(now or now_datetime()))
    )


def expire_large_attachments():
    """Run daily in the scheduler. Only delete a File owned by its message.

    Keep the message and filename for audit. Mark it expired, clear its URL,
    then let Frappe's File controller handle any deduplicated physical blob.
    If the File is reattached elsewhere, skip deletion and log for review.
    """
    now = now_datetime()
    candidates = frappe.get_all(
        MESSAGE,
        filters={
            "attachment_expired": 0,
            "attachment_size": [">", 0],
            "attachment_expires_on": ["<=", now],
            "attachment_file_id": ["is", "set"],
        },
        fields=["name"],
        order_by="attachment_expires_on asc",
        limit_page_length=50,
    )
    completed = 0
    for candidate in candidates:
        # Keep unrelated expiry jobs processing if one record is inconsistent.
        frappe.db.savepoint("mdm_large_attachment_expiry")
        try:
            frappe.db.sql("SELECT name FROM `tabMarina Discussion Message` WHERE name=%s FOR UPDATE", (candidate.name,))
            message = frappe.get_doc(MESSAGE, candidate.name)
            if not (
                int(message.attachment_size or 0) > 0
                and message.attachment_file_id
                and is_past_expiry(message, now)
                and not message.attachment_expired
            ):
                continue
            record = frappe.db.get_value(
                "File",
                message.attachment_file_id,
                ["name", "file_url", "file_size", "is_private", "attached_to_doctype", "attached_to_name"],
                as_dict=True,
            )
            if record:
                if (
                    int(record.is_private or 0) != 1
                    or int(record.file_size or 0) != int(message.attachment_size or 0)
                    or int(record.file_size or 0) <= 0
                    or record.attached_to_doctype != MESSAGE
                    or record.attached_to_name != message.name
                    or record.file_url != message.attachment_url
                ):
                    # Never delete a file whose ownership/linkage has changed.
                    frappe.log_error(
                        "Skipping unexpected File ownership for discussion " + message.name,
                        "Marina discussion attachment expiry",
                    )
                    continue
            # The message has a Link field (attachment_file_id -> File). Frappe
            # correctly raises LinkExistsError if we delete the File first.
            # Clear only this verified reference before calling delete_doc;
            # do NOT bypass Frappe's other link checks with ignore_links.
            # Both database changes remain inside the same savepoint, so a
            # failed delete restores the message's link and expiry state.
            frappe.db.set_value(
                MESSAGE,
                message.name,
                {
                    "attachment_file_id": None,
                    "attachment_url": "",
                    "attachment_expired": 1,
                },
                update_modified=False,
            )
            if record:
                frappe.delete_doc("File", record.name, ignore_permissions=True)
            # A previously removed File can still be marked expired; that makes
            # the audit state accurate without affecting unrelated files.
            completed += 1
        except Exception:
            frappe.db.rollback(save_point="mdm_large_attachment_expiry")
            frappe.log_error(frappe.get_traceback(), "Marina discussion attachment expiry")
    return completed
