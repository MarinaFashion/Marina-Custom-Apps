import frappe
from frappe.model.document import Document


class FactoryList(Document):
    def validate(self):
        self.factory_name = (self.factory_name or "").strip()
        if not self.factory_name or len(self.factory_name) > 140 or any(ord(c) < 32 for c in self.factory_name):
            frappe.throw("Factory Name must be between 1 and 140 characters without control characters")
        facilities = set()
        for row in self.get("facilities") or []:
            row.facility_name = (row.facility_name or "").strip()
            if not row.facility_name or row.facility_name.casefold() in facilities:
                frappe.throw("Facility names must be nonempty and unique within the factory")
            facilities.add(row.facility_name.casefold())
        primary = 0
        for row in self.get("contacts") or []:
            row.contact_person = (row.contact_person or "").strip()
            row.facility_name = (row.facility_name or "").strip()
            if not row.contact_person:
                frappe.throw("Contact Person is required")
            if row.facility_name and row.facility_name.casefold() not in facilities:
                frappe.throw("Contact facility must match a Facility Name in this factory")
            primary += int(row.is_primary or 0)
        if primary > 1:
            frappe.throw("Select only one Primary Contact per factory")

    def on_update(self):
        if hasattr(frappe.local, "_marina_factory_choice_cache"):
            delattr(frappe.local, "_marina_factory_choice_cache")
