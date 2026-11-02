import frappe
from frappe.model.document import Document
from marina_custom_apps.design_management.discussions import require_internal_write


class MarinaDiscussionReceipt(Document):
    def validate(self):
        require_internal_write()

    def on_trash(self):
        require_internal_write()


def on_doctype_update():
    frappe.db.add_unique("Marina Discussion Receipt", ["message", "user"])
    frappe.db.add_index("Marina Discussion Receipt", ["user", "is_mention", "is_read"])
