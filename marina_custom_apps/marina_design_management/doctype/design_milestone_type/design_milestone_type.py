"""Fresh Release 22 milestone configuration.

This DocType intentionally does not import old sequence, legacy assignment,
completion workflow or old QC milestone helpers.
"""
import frappe
from frappe.model.document import Document

from marina_custom_apps.design_management.clean_milestones.rules import (
    ConfigurationError, validate_master_definition,
)


class DesignMilestoneType(Document):
    def validate(self):
        if not self.milestone_type or not self.milestone_type.strip():
            frappe.throw("Milestone name is required")
        try:
            weight = self.completion_weight_days or 0
            if (isinstance(weight, bool) or int(weight) != float(weight)
                    or not 0 <= int(weight) <= 3650):
                frappe.throw("Completion Weight Override must be a whole number between 0 and 3650")
            roles, evidence_types = validate_master_definition({
                "name": self.name or self.milestone_type,
                "start_with_design_creation": self.start_with_design_creation,
                "depends_on_type": self.depends_on_type,
                "trigger_status": self.r22_trigger_status,
                "steps": [r.as_dict() for r in self.get("workflow_steps") or []],
            })
        except ConfigurationError as exc:
            frappe.throw(str(exc))
        if roles:
            active_roles = set(frappe.get_all("Design Module Role",
                filters={"name": ["in", sorted(roles)], "enabled": 1},
                pluck="name", limit_page_length=len(roles)))
            if active_roles != roles:
                frappe.throw("Inactive or missing Module Role(s): " +
                             ", ".join(sorted(roles - active_roles)))
        if evidence_types:
            active_types = set(frappe.get_all("Design Document Type",
                filters={"name": ["in", sorted(evidence_types)], "is_active": 1},
                pluck="name", limit_page_length=len(evidence_types)))
            if active_types != evidence_types:
                frappe.throw("Inactive or missing Evidence Type(s): " +
                             ", ".join(sorted(evidence_types - active_types)))
        if self.depends_on_type and self.depends_on_type == self.name:
            frappe.throw("Milestone cannot trigger itself")
