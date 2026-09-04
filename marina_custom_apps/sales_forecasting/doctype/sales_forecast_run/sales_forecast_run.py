import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class SalesForecastRun(Document):
    def validate(self):
        if not self.is_new():
            stored_status = frappe.db.get_value(self.doctype, self.name, "status")
            if stored_status == "Completed":
                frappe.throw(
                    _("Completed Forecast Runs are immutable. Create a new Forecast Run instead.")
                )

        cfg = frappe.get_single("Sales Forecast Settings")
        self.company = self.company or cfg.company or "Marina"
        self.model_name = cfg.model_name or "Marina Analog Ensemble v1"
        if self.forecast_from and self.forecast_to and getdate(self.forecast_to) < getdate(self.forecast_from):
            frappe.throw(_("Forecast To must be on or after Forecast From."))
        if self.run_type == "Backtest" and self.as_of_date and self.forecast_from:
            if getdate(self.forecast_from) <= getdate(self.as_of_date):
                frappe.throw(_("Backtest Forecast From must be after Information Available Through."))
        if self.is_new():
            self.status = "Draft"

    def on_trash(self):
        stored_status = frappe.db.get_value(self.doctype, self.name, "status")
        if stored_status == "Completed":
            frappe.throw(
                _("Completed Forecast Runs cannot be deleted because they are part of the forecast audit trail.")
            )
        frappe.db.delete("Sales Forecast Result", {"forecast_run": self.name})
