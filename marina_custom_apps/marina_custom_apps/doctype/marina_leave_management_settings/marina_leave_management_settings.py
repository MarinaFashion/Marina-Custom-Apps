"""Settings intentionally fail closed until HRMS posting support is certified."""
import frappe
from frappe import _
from frappe.model.document import Document


class MarinaLeaveManagementSettings(Document):
    def validate(self):
        roles = set(frappe.get_roles(frappe.session.user))
        if frappe.session.user != "Administrator" and not roles.intersection(
            {"HR Manager", "System Manager"}
        ):
            frappe.throw(_("HR Manager or System Manager required"), frappe.PermissionError)
        if self.enable_leave_posting:
            frappe.throw(_(
                "Leave posting is not yet available. Verify HRMS earned-leave "
                "compatibility, historical cutover, and employee/month idempotency "
                "before enabling this setting."
            ))
        self.posting_status_note = (
            "Phase 4B preflight only: posting is disabled. "
            "This setting creates no allocations or ledger entries."
        )
