"""Settings for module-specific user roles, factories and Item field mappings.

No old milestone confirmer, legacy staff lists, reminder or delegation fields.
"""
import frappe
from frappe.model.document import Document


class DesignManagementSettings(Document):
    def validate(self):
        prior = self.get_doc_before_save()
        if prior and (frappe.session.user != "Administrator"
                      and "System Manager" not in frappe.get_roles()):
            if (int(self.module_rbac_enabled or 0) != int(prior.module_rbac_enabled or 0)
                or sorted((r.user, r.module_role, r.active) for r in (
                    self.module_user_roles or [])) != sorted(
                    (r.user, r.module_role, r.active) for r in (
                        prior.module_user_roles or []))):
                frappe.throw("Only System Manager may modify Module Role assignments",
                             frappe.PermissionError)
        # Only administrators may change the conversation retention policy.
        # No existing message or expiry timestamp is updated by saving settings.
        for fieldname, minimum, maximum in (
            ("discussion_retention_threshold_mb", 1, 500),
            ("discussion_retention_days", 1, 365),
        ):
            value = self.get(fieldname)
            if value is None or str(value).strip() == "":
                frappe.throw("Set both Discussion Attachment Retention values.")
            try:
                parsed = int(value)
            except (ValueError, TypeError):
                frappe.throw("Discussion retention settings must be whole numbers.")
            if parsed < minimum or parsed > maximum or str(value).strip() not in (str(parsed),):
                frappe.throw(
                    f"{self.meta.get_label(fieldname)} must be a whole number from {minimum} to {maximum}."
                )
        if prior and any(
            int(self.get(fieldname) or 0) != int(prior.get(fieldname) or 0)
            for fieldname in ("discussion_retention_threshold_mb", "discussion_retention_days")
        ):
            if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
                frappe.throw("Only System Manager may modify chat attachment retention.", frappe.PermissionError)
        from marina_custom_apps.design_management.security.role_access import validate_settings
        validate_settings(self)
        users = sorted({r.user for r in (self.module_user_roles or []) if r.user})
        if users:
            records = frappe.get_all("User", filters={"name": ["in", users]},
                fields=["name", "username"], limit_page_length=len(users))
            names = {r.name:(r.username or "").strip() for r in records}
            for row in self.module_user_roles or []:
                row.user_name = names.get(row.user) or "Username not configured"
        from marina_custom_apps.design_management.item_field_mapping import validate_item_field_mappings
        validate_item_field_mappings(self.get("item_field_mappings") or [])

    def on_update(self):
        prior = self.get_doc_before_save()
        from marina_custom_apps.design_management.security.module_role_sync import sync_user_roles
        sync_user_roles(self, prior)
