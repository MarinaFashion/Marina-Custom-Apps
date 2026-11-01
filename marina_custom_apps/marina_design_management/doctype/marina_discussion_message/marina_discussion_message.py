import frappe
from frappe.model.document import Document
from marina_custom_apps.design_management.discussions import require_internal_write


class MarinaDiscussionMessage(Document):
    def validate(self):
        require_internal_write()

    def on_trash(self):
        require_internal_write()


def on_doctype_update():
    frappe.db.add_index("Marina Discussion Message", ["reference_doctype", "reference_name", "creation"])
