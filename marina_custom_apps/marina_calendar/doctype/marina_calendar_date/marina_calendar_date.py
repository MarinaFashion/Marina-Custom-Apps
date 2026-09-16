import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class MarinaCalendarDate(Document):
    def autoname(self):
        if self.date:
            self.name = str(getdate(self.date))

    def validate(self):
        if not self.date:
            return
        value = getdate(self.date)
        if not self.is_new():
            stored_date = frappe.db.get_value(self.doctype, self.name, "date")
            if stored_date and getdate(stored_date) != value:
                frappe.throw(_("Date cannot be changed after a Marina Calendar Date is created."))
        duplicate = frappe.db.exists(
            self.doctype,
            {"date": value, "name": ["!=", self.name]},
        )
        if duplicate:
            frappe.throw(_("A Marina Calendar Date already exists for {0}.").format(value))
        self.month_name = value.strftime("%B")
        self.week_day = value.strftime("%A")
        names = []
        for row in self.events or []:
            if row.event_name and row.event_name not in names:
                names.append(row.event_name)
        self.event_count = len(self.events or [])
        self.event_summary = ", ".join(names)
