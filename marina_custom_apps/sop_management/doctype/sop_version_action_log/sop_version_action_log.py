import frappe
from frappe import _
from frappe.model.document import Document


class SOPVersionActionLog(Document):
    def before_insert(self):
        if not frappe.flags.in_sop_version_action_log:
            frappe.throw(
                _("SOP Version Action Logs are created only by controlled system actions."),
                frappe.PermissionError,
            )

    def validate(self):
        if not self.is_new() and not frappe.flags.in_sop_version_action_log:
            frappe.throw(_("SOP Version Action Logs are immutable."))

    def on_trash(self):
        frappe.throw(_("SOP Version Action Logs cannot be deleted."))
