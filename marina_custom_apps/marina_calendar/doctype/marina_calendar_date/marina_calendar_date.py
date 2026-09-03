import frappe
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
        self.month_name = value.strftime("%B")
        self.week_day = value.strftime("%A")
        names = []
        for row in self.events or []:
            if row.event_name and row.event_name not in names:
                names.append(row.event_name)
        self.event_count = len(self.events or [])
        self.event_summary = ", ".join(names)
