"""Explicitly gated one-employee posting pilot; never authorizes scheduling."""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class MarinaLeaveManagementSettings(Document):
    def validate(self):
        roles = set(frappe.get_roles(frappe.session.user))
        if frappe.session.user != "Administrator" and not roles.intersection(
            {"HR Manager", "System Manager"}
        ):
            frappe.throw(_("HR Manager or System Manager required"), frappe.PermissionError)
        if self.enable_leave_posting:
            # The pilot must not be enabled simply by a deploy or default setting.
            if not frappe.local.site.endswith("demo.frappe.cloud"):
                frappe.throw(_("Pilot posting is restricted to the Marina demo site"))
            if not self.pilot_employee or not self.cutover_date or not self.allocation_end_date:
                frappe.throw(_("Pilot employee, cutover date and allocation end date are mandatory"))
            if not self.cutover_confirmed:
                frappe.throw(_("Historical balance cutover must be reviewed and confirmed"))
            if getdate(self.allocation_end_date) <= getdate(self.cutover_date):
                frappe.throw(_("Allocation end date must be after cutover date"))
            if frappe.db.get_value("Leave Type", "Paid Leave", "is_earned_leave"):
                frappe.throw(_("Disable native Paid Leave earned accrual before enabling pilot"))
            self.posting_status_note = (
                "DEMO PILOT ONLY. Only the selected employee may be posted via "
                "the explicit Post Selected Employee action. No scheduler is enabled."
            )
        else:
            self.posting_status_note = (
                "Posting disabled. Preview, preflight and dry-run make no changes "
                "to Leave Allocations or Leave Ledger."
            )
