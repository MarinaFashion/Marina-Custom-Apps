"""Design Code and practical Production Item planning.

The planned item codes are *reservations*, not ERPNext Item creation.
- One row per planned design/color Item Code.
- One separate (hidden) size allocation table keyed to that row.
- Global DB uniqueness on Design Production Item.item_code is the race-safe
  final guard against reserving the same code in multiple Design Codes.
- Moving to In Production enforces a complete breakdown and valid direct cost.
"""
import re
from math import isfinite
from uuid import uuid4

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt, nowdate, getdate


MAX_PRODUCTION_ITEMS = 200
MAX_SIZE_ROWS = 5000


class DesignCode(Document):
    def before_validate(self):
        from marina_custom_apps.design_management.clean_milestones.team import (
            snapshot_design, sync_legacy_owners,
        )
        if self.is_new() and self.mood_board:
            snapshot_design(self)
        # The snapshot is authoritative. These hidden compatibility fields
        # remain synchronized for reports, filters and existing integrations.
        if (self.is_new() or self.r22_team_snapshot_applied
                or self.get("r22_team_assignments")):
            sync_legacy_owners(self)
        # User may backdate initial planning to the real Tech Pack release.
        # Never overwrite a user-selected Creation Date on first Save.
        if self.is_new() and not self.creation_date:
            self.creation_date = nowdate()
        if self.mood_board:
            board = frappe.get_doc("Mood Board", self.mood_board)
            self.year, self.season, self.collection, self.drop = (
                board.year, board.season, board.collection, board.drop)
            if self.is_new() and not self.display_date:
                self.display_date = board.display_date
        for row in self.get("production_items") or []:
            if not row.production_key:
                row.production_key = uuid4().hex

    def validate(self):
        from marina_custom_apps.design_management.clean_milestones.team import validate_design
        validate_design(self)
        if (self.get("report_position") or 0) < 0:
            frappe.throw("Report Position cannot be negative")
        if not self.mood_board:
            frappe.throw("Mood Board is required")
        if not frappe.has_permission("Mood Board", "read", doc=self.mood_board):
            frappe.throw("Cannot access this Mood Board", frappe.PermissionError)
        before = self.get_doc_before_save() if not self.is_new() else None
        self._validate_creation_date(before)
        if before and cint(before.get("tech_pack_not_required")) != cint(
                self.get("tech_pack_not_required")):
            # Freeze the exception at plan creation to avoid retroactively
            # changing the evidence basis of completed milestones.
            frappe.db.sql(
                "SELECT name FROM `tabDesign Code` WHERE name=%s FOR UPDATE",
                (self.name,),
            )
            if frappe.db.exists("Design Milestone Plan Entry", {
                    "design_code": self.name}):
                frappe.throw(
                    "Tech Pack Not Required cannot change after milestones are created"
                )
        previous_fabric = (before.get("fabric_approval_required") or "") if before else ""
        selected_fabric = self.get("fabric_approval_required") or ""
        if selected_fabric != previous_fabric:
            from marina_custom_apps.design_management.security.role_access import can_action
            action = ("Set Initial Fabric Approval" if not previous_fabric
                      and selected_fabric else "Change Fabric Approval")
            if not can_action(action, frappe.session.user):
                frappe.throw("Missing Design Action: " + action, frappe.PermissionError)
            if before:
                # Updating a saved Design Code must never silently rewrite an
                # already-created workflow. Use the controlled Change action.
                frappe.db.sql(
                    "SELECT name FROM `tabDesign Code` WHERE name=%s FOR UPDATE",
                    (self.name,),
                )
                if frappe.db.exists("Design Milestone Plan Entry", {
                        "design_code": self.name}):
                    frappe.throw(
                        "Fabric Approval cannot change after milestones are created"
                    )
        if before:
            if before.design_number != self.design_number:
                frappe.throw("Design Number cannot be changed")
            if before.mood_board != self.mood_board:
                frappe.throw("Mood Board cannot be changed after creation")
            if (before.production_currency != self.production_currency
                    and before.development_stage == "In Production"):
                frappe.throw("Production Currency cannot change once the Design is In Production")

        from marina_custom_apps.design_management.factory_options import check_factory
        if self.factory:
            check_factory(self.factory,
                          existing_value=before.factory if before else None)
        if not self.category or not self.subcategory:
            frappe.throw("Fashion Category and Subcategory are required")
        if frappe.db.get_value("Marina Fashion Category", self.category, "parent_category"):
            frappe.throw("Select a top-level Fashion Category")
        if frappe.db.get_value(
            "Marina Fashion Category", self.subcategory, "parent_category"
        ) != self.category:
            frappe.throw("Invalid Fashion Subcategory")

        known_abbr = self._normalize_design_sizes()
        allowed_sizes = set()
        for row in self.sizes or []:
            if not row.size or row.size in allowed_sizes:
                frappe.throw("Design Sizes must be nonempty and unique")
            allowed_sizes.add(row.size)
            if row.size not in known_abbr:
                frappe.throw("Unknown ERPNext Size Item Attribute value: " + row.size)
        active_pantones=self._fill_pantone_swatches()
        for component in self.pantone_components or []:
            if component.pantone not in active_pantones:
                frappe.throw("Inactive or unknown Pantone")

        self.validate_production_items(before, allowed_sizes)
        if before:
            from marina_custom_apps.design_management.item_creation import prevent_linked_mutation
            prevent_linked_mutation(self, before)

    def _validate_creation_date(self, before):
        """Protect the planning baseline from edits after Create Milestones.

        The Design row lock is shared with create_plan(), so concurrent
        submissions serialize instead of silently shifting milestone dates.
        """
        if not self.creation_date:
            frappe.throw("Creation Date is required for milestone planning")
        if getdate(self.creation_date) > getdate(nowdate()):
            frappe.throw("Creation Date cannot be in the future")
        if before and str(before.creation_date or "")[:10] != str(self.creation_date or "")[:10]:
            if not frappe.db.sql(
                "SELECT name FROM `tabDesign Code` WHERE name=%s FOR UPDATE",
                (self.name,)
            ):
                frappe.throw("Design Code not found")
            if frappe.db.exists("Design Milestone Plan Entry", {
                "design_code": self.name
            }):
                frappe.throw(
                    "Creation Date cannot change after milestones are created"
                )

    def on_update(self):
        # A new responsibility snapshot is the source of truth for custody.
        # Reassign only currently active work; keep all earlier history.
        from marina_custom_apps.design_management.clean_milestones.team import sync_active_custody
        sync_active_custody(self)
        # Designer may be assigned after initial creation. Link a Tech Pack
        # only when the design gets its first Designer, not on reassignment:
        # historical files must never be silently rewritten.
        before = self.get_doc_before_save()
        if before and not before.designer and self.designer:
            from marina_custom_apps.design_management.clean_milestones.tech_pack_matching import link_design
            link_design(self)

    def after_insert(self):
        # New Design Codes may already have a Designer from their Mood Board.
        from marina_custom_apps.design_management.clean_milestones.tech_pack_matching import link_design
        link_design(self)

    def _normalize_design_sizes(self):
        """Normalize old Size descriptions and validate ERPNext Size abbreviations."""
        from marina_custom_apps.design_management.setup.size_reference import get_size_catalog
        selected = self.get("sizes") or []
        allocation = self.get("production_size_breakdown") or []
        if not selected and not allocation:
            return set()
        by_abbr, by_label = get_size_catalog()
        for row in selected:
            old = (row.size or "").strip()
            row.size = old if old in by_abbr else by_label.get(old, old)
            row.size_description = by_abbr.get(row.size, "")
        for row in allocation:
            old = (row.size or "").strip()
            row.size = old if old in by_abbr else by_label.get(old, old)
        return set(by_abbr)

    def _fill_pantone_swatches(self):
        rows=self.get("pantone_components") or []
        if not rows:
            return set()
        names=list({r.pantone for r in rows if r.pantone})
        records=frappe.get_all("Marina Pantone",
            filters={"name":["in",names]},
            fields=["name","color_image","is_active"],limit_page_length=len(names))
        images={r.name:r.color_image for r in records}
        for row in rows:
            row.color_image=images.get(row.pantone)
        return {r.name for r in records if r.is_active}

    def validate_production_items(self, before, allowed_sizes):
        items = self.get("production_items") or []
        sizes = self.get("production_size_breakdown") or []
        if len(items) > MAX_PRODUCTION_ITEMS or len(sizes) > MAX_SIZE_ROWS:
            frappe.throw("Too many production rows in one Design Code")

        in_production = self.development_stage == "In Production"
        if in_production and not items:
            frappe.throw("Add at least one Production Item before setting In Production")
        if self.production_currency:
            if not frappe.db.exists("Currency", self.production_currency):
                frappe.throw("Unknown Production Currency")
        elif in_production:
            frappe.throw("Select a Production Currency before setting In Production")

        previous_by_name = {
            row.name: row for row in (before.production_items or [])
        } if before else {}
        keys = set()
        previous_keys = {r.production_key for r in (before.production_items or [])} if before else set()
        codes = set()
        current_by_code = {}
        for row in items:
            row.item_code = (row.item_code or "").strip()
            if not row.item_code or len(row.item_code) > 140:
                frappe.throw("Each Production Item requires an Item Code (max. 140 characters)")
            if any(ord(ch) < 32 for ch in row.item_code):
                frappe.throw("Item Codes cannot contain tabs or newlines")
            if row.item_code.casefold() in codes:
                frappe.throw("Duplicate Planned Item Code in this Design: " + row.item_code)
            codes.add(row.item_code.casefold())
            current_by_code[row.item_code] = row
            if not re.fullmatch(r"[a-f0-9]{32}", row.production_key or ""):
                frappe.throw("Invalid internal Production Item reference")
            if row.production_key in keys:
                frappe.throw("Duplicate internal Production Item reference")
            keys.add(row.production_key)
            old_row = previous_by_name.get(row.name)
            if old_row and row.production_key != old_row.production_key:
                frappe.throw("Production Item references cannot be changed")
            if not old_row and row.production_key in previous_keys:
                frappe.throw("Production Item reference is already assigned to another row")
            unit_cost = flt(row.unit_cost, 2)
            if not isfinite(unit_cost):
                frappe.throw("Unit Direct Cost must be a finite number")
            if unit_cost < 0:
                frappe.throw("Unit Direct Cost cannot be negative")
            if in_production and unit_cost <= 0:
                frappe.throw("Each Production Item must have a positive Unit Direct Cost")
            row.unit_cost = unit_cost
            row.currency = self.production_currency

        # Batched duplicate checks. Existing, unchanged planned codes are
        # grandfathered if another process has since created the ERPNext Item.
        new_codes = [
            row.item_code for row in items
            if not previous_by_name.get(row.name)
            or previous_by_name[row.name].item_code != row.item_code
        ]
        if new_codes:
            created_items = frappe.get_all(
                "Item", filters={"item_code": ["in", new_codes]},
                pluck="item_code", limit_page_length=len(new_codes),
            )
            if created_items:
                frappe.throw(
                    "Already exists in ERPNext Item: " + ", ".join(created_items[:10])
                )

        if current_by_code:
            existing = frappe.get_all(
                "Design Production Item",
                filters={"item_code": ["in", list(current_by_code)],
                         "parenttype": "Design Code", "parentfield": "production_items"},
                fields=["name", "parent", "item_code"],
                limit_page_length=len(current_by_code),
            )
            for reserved in existing:
                current = current_by_code.get(reserved.item_code)
                if current and (reserved.parent != self.name or reserved.name != current.name):
                    frappe.throw(
                        "Planned Item Code is already reserved by Design Code: " + reserved.item_code
                    )

        qty_by_key = {key: 0 for key in keys}
        allocated = set()
        for row in sizes:
            if row.production_key not in keys:
                frappe.throw("Size Breakdown contains an unlinked Production Item")
            if not row.size or row.size not in allowed_sizes:
                frappe.throw("Size Breakdown must use Sizes configured in this Design Code")
            pair = (row.production_key, row.size)
            if pair in allocated:
                frappe.throw("Duplicate Size in one Production Item")
            allocated.add(pair)
            original = flt(row.qty)
            qty = cint(row.qty)
            if qty < 0 or original != qty:
                frappe.throw("Production Size Qty must be a nonnegative whole number")
            row.qty = qty
            qty_by_key[row.production_key] += qty

        quantity_total = 0
        cost_total = 0
        for row in items:
            row.quantity = qty_by_key[row.production_key]
            row.total_cost = flt(row.quantity * flt(row.unit_cost, 2), 2)
            quantity_total += row.quantity
            cost_total += row.total_cost
            if in_production and row.quantity <= 0:
                frappe.throw("Enter a positive Size Breakdown quantity for " + row.item_code)
        self.production_total_qty = quantity_total
        self.production_total_cost = flt(cost_total, 2)

        # This DocType intentionally does NOT create or modify ERPNext Items.

    def on_trash(self):
        """Apply identical audited cleanup for Form and List bulk Delete.

        Frappe v15 invokes on_trash for each standard list-selected record
        after checking Delete permission and acquiring a row lock. This hook
        also checks the Marina module action permission and archives related
        milestone history before unlinking document assignments.
        """
        from marina_custom_apps.design_management.design_deletion import (
            cleanup_before_design_trash,
        )
        reason=getattr(frappe.flags, "marina_design_delete_reason", None)
        impact=cleanup_before_design_trash(self, reason=reason)
        # The Form action reads this result; normal list deletion ignores it.
        frappe.flags.marina_design_delete_result={
            "deleted":self.name, "impact":impact,
        }


@frappe.whitelist()
def can_edit_creation_date(design_code):
    """UI-only capability; server validate() remains the final protection.

    Queries the indexed milestone plan association once per form refresh.
    Any user must have standard Design Code Write permission to unlock.
    """
    if not isinstance(design_code, str) or not design_code:
        return False
    design = frappe.get_doc("Design Code", design_code)
    design.check_permission("write")
    return not bool(frappe.db.exists(
        "Design Milestone Plan Entry", {"design_code": design_code}
    ))

