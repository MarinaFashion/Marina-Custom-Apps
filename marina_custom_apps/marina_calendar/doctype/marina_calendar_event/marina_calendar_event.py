import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class MarinaCalendarEvent(Document):
    def validate(self):
        if not self.start_date:
            frappe.throw(_("Start Date is required."))
        if not self.end_date:
            self.end_date = self.start_date
        if getdate(self.end_date) < getdate(self.start_date):
            frappe.throw(_("End Date cannot be before Start Date."))

        if self.scope == "Branch" and not self.branch:
            frappe.throw(_("Branch is required when Scope is Branch."))
        if self.scope == "City" and not self.city:
            frappe.throw(_("City is required when Scope is City."))

        if self.scope == "Company":
            self.city = ""
            self.branch = ""
        elif self.scope == "City":
            self.branch = ""

        # A declared closure is operational truth, not merely a soft demand signal.
        # Keep it forecast-relevant and consistently classified.
        if self.store_trading_status == "Closed":
            self.forecast_relevant = 1
            self.expected_sales_impact = "Negative"
            self.impact_strength = "High"

    def on_update(self):
        from marina_custom_apps.marina_calendar.services import sync_event_dates
        sync_event_dates(self.name)

    def on_trash(self):
        from marina_custom_apps.marina_calendar.services import remove_event_links
        remove_event_links(self.name)
