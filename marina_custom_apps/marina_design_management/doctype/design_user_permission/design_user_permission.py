import frappe
from frappe import _
from frappe.model.document import Document
from marina_custom_apps.design_management.security.user_permissions import (
    DOCS, ACTIONS, CUSTODY_ACTIONS, invalidate,
)


class DesignUserPermission(Document):
    def before_insert(self):
        # New profiles are opt-in and have no grants until explicitly edited.
        # Prefill complete, visible permission tables for a simple checkbox UI.
        if not self.get("document_permissions"):
            for doctype in sorted(DOCS):
                if frappe.db.exists("DocType", doctype):
                    self.append("document_permissions", {
                        "resource_doctype": doctype,
                        "read": 0, "create": 0, "write": 0, "delete": 0,
                    })
        if not self.get("action_permissions"):
            for action in sorted(ACTIONS):
                self.append("action_permissions", {
                    "action_key": action, "access": "Not Allowed",
                })

    def validate(self):
        if not frappe.db.get_value("User", self.user, "enabled"):
            frappe.throw(_("Choose an enabled user"))
        if self.user in ("Administrator", "Guest"):
            frappe.throw(_("Do not create individual permission profiles for system users"))
        user_roles = set(frappe.get_roles(self.user))
        if self.enabled and "System Manager" in user_roles:
            frappe.throw(_("System Managers use native administration; individual profiles cannot restrict their global access"))
        if self.enabled and "Marina Design Participant" not in user_roles:
            frappe.throw(_("User must have Marina Design Participant role"))
        documents = set()
        for row in self.get("document_permissions") or []:
            if row.resource_doctype not in DOCS or row.resource_doctype in documents:
                frappe.throw(_("Invalid or repeated Document permission"))
            documents.add(row.resource_doctype)
        actions = set()
        for row in self.get("action_permissions") or []:
            if row.action_key not in ACTIONS or row.action_key in actions:
                frappe.throw(_("Invalid or repeated Action permission"))
            actions.add(row.action_key)
            if row.access not in ("Not Allowed", "Allowed", "Custody Only"):
                frappe.throw(_("Invalid permission value"))
            if row.access == "Custody Only" and row.action_key not in CUSTODY_ACTIONS:
                frappe.throw(_("Custody Only is applicable only to milestone actions"))
        if self.enabled and not documents:
            frappe.throw(_("Configure Document permissions before enabling the user profile"))

    def on_update(self):
        invalidate()
        frappe.clear_cache(user=self.user)

    def on_trash(self):
        invalidate()
        frappe.clear_cache(user=self.user)
