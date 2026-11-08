"""Commercial factory costing and buying-price approval for Marina designs.

Release 1 is independent of milestone completion and ERPNext Buying.
Never write Design Production Items, size allocations, Items or Purchase Orders.
"""
from collections import defaultdict
from math import isfinite

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime, nowdate

MAX_COST_LINES = 200
MAX_PRICE_LINES = 200
STATES = ("Draft", "Pending Approval", "Returned", "Approved", "Superseded", "Cancelled")
EDITABLE_STATES = ("Draft", "Returned")
COST_METHODS = ("Detailed", "Quotation Only", "Hybrid")


def _admin(user=None):
    user = user or frappe.session.user
    return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def _module_roles(user=None):
    """Resolve explicit module assignments even before RBAC is enforced."""
    user = user or frappe.session.user
    cache = getattr(frappe.local, "_marina_cost_role_cache", None)
    if cache is None:
        cache = {}
        frappe.local._marina_cost_role_cache = cache
    if user not in cache:
        rows = frappe.get_all(
            "Design Module User Role",
            filters={"parent": "Design Management Settings",
                     "parenttype": "Design Management Settings",
                     "parentfield": "module_user_roles", "active": 1, "user": user},
            pluck="module_role", limit_page_length=100,
        )
        active = frappe.get_all("Design Module Role",
            filters={"name": ["in", rows], "enabled": 1},
            pluck="name", limit_page_length=len(rows)) if rows else []
        cache[user] = set(active)
    return cache[user]


def _buyer(user=None):
    user = user or frappe.session.user
    from marina_custom_apps.design_management.security.user_permissions import configured
    if configured(user):
        from marina_custom_apps.design_management.security.role_access import can_action
        return can_action("Approve Design Cost Breakdown", user)
    if _admin(user):
        return True
    if "Buying Manager" not in _module_roles(user):
        return False
    from marina_custom_apps.design_management.security.role_access import can_action, enabled
    return not enabled() or can_action("Approve Design Cost Breakdown", user)


def _preparer(design, user=None):
    user = user or frappe.session.user
    from marina_custom_apps.design_management.security.user_permissions import (
        configured, document_allowed,
    )
    if configured(user):
        return bool(document_allowed("Design Cost Breakdown", "create", user)
                    or document_allowed("Design Cost Breakdown", "write", user))
    if _admin(user):
        return True
    if user == design.assigned_merchandiser:
        return True
    return "Head Of Merchandisers" in _module_roles(user)


def _commercial_all_scope(user=None):
    """Costing scope: user matrix when configured, otherwise legacy commercial roles."""
    user = user or frappe.session.user
    from marina_custom_apps.design_management.security.user_permissions import (
        configured, document_allowed,
    )
    if configured(user):
        return document_allowed("Design Cost Breakdown", "read", user) is True
    if _admin(user):
        return True
    eligible = _module_roles(user) & {"Buying Manager", "Head Of Merchandisers"}
    if not eligible:
        return False
    records = frappe.get_all("Design Module Role",
        filters={"name": ["in", sorted(eligible)], "enabled": 1, "scope": "All"},
        pluck="name", limit_page_length=len(eligible))
    return bool(records)


def _allowed_design(design, user=None):
    user = user or frappe.session.user
    return bool(frappe.has_permission("Design Code", "read", doc=design, user=user)
                or _commercial_all_scope(user))


def _variant_map(design):
    by_key = {}
    for item in design.get("production_items") or []:
        if item.production_key:
            by_key[item.production_key] = item
    return by_key


def _number(value, label, *, allow_zero=True):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        frappe.throw(label + " must be numeric.")
    if not isfinite(number) or number < 0 or (not allow_zero and number <= 0):
        frappe.throw(label + " must be a valid positive number.")
    return number


class DesignCostBreakdown(Document):
    def before_insert(self):
        user = frappe.session.user
        design = frappe.get_doc("Design Code", self.design_code)
        if not _allowed_design(design, user) or not _preparer(design, user):
            frappe.throw("Only the assigned Merchandiser or Merchandising Manager may prepare this costing.",
                         frappe.PermissionError)
        # Per-design lock protects monotonically increasing revision numbers
        # and ensures only one editable quotation at a time.
        frappe.db.sql("SELECT name FROM `tabDesign Code` WHERE name=%s FOR UPDATE",
                      (design.name,))
        in_progress = frappe.db.exists("Design Cost Breakdown", {
            "design_code": self.design_code,
            "status": ["in", ["Draft", "Returned", "Pending Approval"]],
        })
        if in_progress:
            frappe.throw("Another Draft, Returned or Pending Approval Cost Breakdown exists for this Design.")
        recent = frappe.get_all("Design Cost Breakdown",
            filters={"design_code": self.design_code}, fields=["revision_no"],
            order_by="revision_no desc", limit_page_length=1)
        self.revision_no = (cint(recent[0].revision_no) if recent else 0) + 1
        self.status = "Draft"
        self.prepared_by = user
        # Never accept client-supplied approval or previous-workflow metadata.
        self.submitted_by = None
        self.submitted_on = None
        self.approved_by = None
        self.approved_on = None
        self.returned_by = None
        self.returned_on = None
        self.return_reason = None
        self.cancelled_by = None
        self.cancelled_on = None
        self.cancellation_reason = None
        self.superseded_by = None
        if self.source_revision:
            if not self.flags.get("cost_revision_clone"):
                frappe.throw("Use Create New Cost Revision instead of setting Based On Version.")
            source = frappe.get_doc("Design Cost Breakdown", self.source_revision)
            if source.design_code != self.design_code or source.status not in ("Approved", "Superseded", "Cancelled"):
                frappe.throw("The source revision does not belong to this Design or is not approved.")

    def validate(self):
        user = frappe.session.user
        if not self.design_code:
            frappe.throw("Select a Design Code.")
        design = frappe.get_doc("Design Code", self.design_code)
        if not _allowed_design(design, user):
            frappe.throw("No access to this Design Code.", frappe.PermissionError)
        before = self.get_doc_before_save() if not self.is_new() else None
        action = self.flags.get("cost_transition")
        # Cancellation is a terminal *approval revocation*, not an edit to
        # previously approved price/quantity lines. Do not recalculate from
        # a Design Code that may have changed since original approval.
        if before and before.status == "Approved" and action == "cancel":
            self._validate_approval_cancellation(before, user)
            return
        if before:
            if self.design_code != before.design_code:
                frappe.throw("A Cost Breakdown cannot be moved to another Design.")
            if self.revision_no != before.revision_no or self.source_revision != before.source_revision:
                frappe.throw("Revision identity cannot be changed.")
            if before.status in ("Approved", "Superseded", "Cancelled"):
                frappe.throw("Approved, Superseded and Cancelled commercial records are immutable.")
            if action is None:
                if self.status != before.status or any(
                    self.get(key) != before.get(key)
                    for key in ("prepared_by", "submitted_by", "submitted_on",
                                "approved_by", "approved_on", "returned_by", "returned_on",
                                "return_reason", "superseded_by",
                                "cancelled_by", "cancelled_on", "cancellation_reason")):
                    frappe.throw("Use Submit, Approve or Return to change the workflow.")
                if before.status == "Pending Approval":
                    frappe.throw("Submitted costings are locked. Return them before editing.")
            elif action not in ("submit", "return", "approve"):
                frappe.throw("Invalid Cost Breakdown workflow transition.")
        elif self.status not in ("Draft", None, ""):
            frappe.throw("New Cost Breakdowns must start as Draft.")

        if action in ("return", "approve"):
            if not _buyer(user):
                frappe.throw("Only the authorized Buying Manager may review Cost Breakdowns.",
                             frappe.PermissionError)
        elif not _preparer(design, user):
            frappe.throw("Only the assigned Merchandiser or Merchandising Manager may edit this costing.",
                         frappe.PermissionError)

        self.mood_board = design.mood_board
        self.design_image = design.image
        self.merchandiser = design.assigned_merchandiser
        if not self.factory:
            self.factory = design.factory
        if not self.quotation_date:
            self.quotation_date = nowdate()
        if self.costing_method not in COST_METHODS:
            frappe.throw("Choose Detailed, Quotation Only or Hybrid costing.")
        if self.factory and not frappe.db.get_value("Factory List", self.factory, "is_active"):
            frappe.throw("Choose an active factory.")
        if self.currency and not frappe.db.exists("Currency", self.currency):
            frappe.throw("Unknown quotation Currency.")
        rate = _number(self.exchange_rate_sar, "Exchange Rate")
        if rate:
            self.exchange_rate_sar = flt(rate, 6)
        if len(self.get("cost_components") or []) > MAX_COST_LINES:
            frappe.throw("Maximum 200 Cost Component lines.")
        if len(self.get("price_qty_lines") or []) > MAX_PRICE_LINES:
            frappe.throw("Maximum 200 Price and Qty lines.")
        self._calculate(design)
        if action in ("submit", "approve"):
            self._approval_checks(design)

    def _validate_approval_cancellation(self, before, user):
        """Reject every attempted commercial edit during approval cancellation.

        Only the three cancellation audit fields and terminal status may
        change. All other parent fields and child tables must match the
        original approved document exactly.
        """
        if not _buyer(user):
            frappe.throw("Only an authorized Buying Manager can cancel approval.",
                         frappe.PermissionError)
        if user != "Administrator" and user in (before.prepared_by, before.submitted_by):
            frappe.throw("The preparer cannot cancel their own approval.",
                         frappe.PermissionError)
        if self.status != "Cancelled":
            frappe.throw("Cancellation must set status to Cancelled.")
        if self.cancelled_by != user or not self.cancelled_on:
            frappe.throw("Cancellation must record the actor and actual timestamp.")
        reason = (self.cancellation_reason or "").strip()
        if not 10 <= len(reason) <= 500 or reason != self.cancellation_reason:
            frappe.throw("Cancellation requires a reason of 10–500 characters.")
        protected = ("status", "cancelled_by", "cancelled_on", "cancellation_reason")
        for field in self.meta.fields:
            name = field.fieldname
            if not name or name in protected or field.fieldtype in (
                    "Section Break", "Column Break", "Tab Break", "HTML", "Button"):
                continue
            if field.fieldtype == "Table":
                # Every child row, including its original identity and order,
                # must be retained. Neither figures nor audit links may change.
                old_rows = [row.as_dict() for row in before.get(name) or []]
                new_rows = [row.as_dict() for row in self.get(name) or []]
                if old_rows != new_rows:
                    frappe.throw("Cannot modify cost or price rows while cancelling approval.")
            elif self.get(name) != before.get(name):
                frappe.throw("Cannot modify " + field.label + " while cancelling approval.")

    def _calculate(self, design):
        keys = _variant_map(design)
        code_seen = set()
        variants = {}
        self.total_qty = 0
        self.total_quoted_value = 0
        self.total_purchase_value = 0
        for item in self.get("price_qty_lines") or []:
            code = (item.variant_code or "").strip()
            if not code or len(code) > 140:
                frappe.throw("Each Price and Qty line requires a Color / Variant (max 140 chars).")
            if code.casefold() in code_seen:
                frappe.throw("Duplicate Color / Variant in Price and Qty: " + code)
            code_seen.add(code.casefold())
            item.variant_code = code
            qty = _number(item.proposed_qty, "Proposed Qty")
            moq = _number(item.moq, "MOQ")
            if int(qty) != qty or int(moq) != moq:
                frappe.throw("Quantity and MOQ must be whole numbers.")
            item.proposed_qty, item.moq = int(qty), int(moq)
            quoted = _number(item.supplier_quoted_price, "Supplier Quoted Price")
            negotiated = _number(item.negotiated_unit_price, "Negotiated Unit Price")
            item.supplier_quoted_price = flt(quoted, 4)
            item.negotiated_unit_price = flt(negotiated, 4)
            if item.production_key:
                ref = keys.get(item.production_key)
                if not ref:
                    frappe.throw("A linked Production Item was removed. Clear the link and review the costing.")
                if code.casefold() != str(ref.color_name or ref.item_code).strip().casefold():
                    frappe.throw("Linked Production Item color differs from costing variant: " + code)
                item.planned_item_code = ref.item_code
            elif item.planned_item_code:
                frappe.throw("An unlinked variant cannot claim an existing Planned Item Code.")
            item.quoted_value = flt(item.supplier_quoted_price * qty, 2)
            item.purchase_value = flt(item.negotiated_unit_price * qty, 2)
            item.discount_percent = flt(
                (quoted - negotiated) * 100 / quoted if quoted else 0, 2)
            self.total_qty += item.proposed_qty
            self.total_quoted_value += item.quoted_value
            self.total_purchase_value += item.purchase_value
            variants[code.casefold()] = item

        assigned = defaultdict(float)
        for line in self.get("cost_components") or []:
            if not (line.description or "").strip() or not line.cost_category:
                frappe.throw("Each cost component needs a category and description.")
            if line.applies_to not in ("All Variants", "Specific Variant"):
                frappe.throw("Invalid component applicability.")
            if line.cost_basis not in ("Per Piece", "Per Order"):
                frappe.throw("Invalid component cost basis.")
            consume = _number(line.consumption, "Component Consumption", allow_zero=False)
            unit_rate = _number(line.unit_rate, "Component Rate")
            waste = _number(line.wastage_percent, "Wastage %")
            if waste > 100:
                frappe.throw("Component wastage cannot exceed 100%.")
            raw = consume * unit_rate * (1 + waste / 100)
            if line.applies_to == "Specific Variant":
                target = variants.get((line.variant_code or "").strip().casefold())
                if not target:
                    frappe.throw("Specific Variant cost component must match a Price and Qty line.")
                eligible = [target]
            else:
                if line.variant_code:
                    frappe.throw("Clear Variant Code when a component applies to All Variants.")
                eligible = list(variants.values())
            eligible_qty = sum(row.proposed_qty for row in eligible)
            if line.cost_basis == "Per Order" and not eligible_qty:
                frappe.throw("Per Order costs require a positive applicable quantity.")
            line.component_amount = flt(raw, 4)
            if eligible:
                unit_cost = raw / eligible_qty if line.cost_basis == "Per Order" else raw
                for row in eligible:
                    assigned[row.variant_code.casefold()] += unit_cost

        estimated_order_value = 0.0
        for item in self.get("price_qty_lines") or []:
            cost = flt(assigned[item.variant_code.casefold()], 4)
            item.estimated_component_cost = cost
            item.cost_difference = flt(item.negotiated_unit_price - cost, 4) if (
                self.get("cost_components") or []) else 0
            estimated_order_value += cost * item.proposed_qty

        self.estimated_component_value = flt(estimated_order_value, 2)
        self.total_quoted_value = flt(self.total_quoted_value, 2)
        self.total_purchase_value = flt(self.total_purchase_value, 2)
        self.savings_value = flt(self.total_quoted_value - self.total_purchase_value, 2)
        self.savings_percent = flt(
            100 * self.savings_value / self.total_quoted_value
            if self.total_quoted_value else 0, 2)
        self.weighted_unit_price = flt(
            self.total_purchase_value / self.total_qty if self.total_qty else 0, 4)
        self.estimated_sar_value = flt(
            self.total_purchase_value * flt(self.exchange_rate_sar or 0, 6), 2)

    def _approval_checks(self, design):
        if not self.factory or not self.currency or not self.quotation_date:
            frappe.throw("Factory, Currency and Quotation Date are required for approval.")
        if not self.quotation_reference and not self.quotation_attachment:
            frappe.throw("Provide a factory quotation reference or attach the quotation.")
        if self.quotation_attachment:
            url = self.quotation_attachment
            if (not url.startswith(("/files/", "/private/files/")) or
                    ".." in url or "?" in url or "#" in url or
                    not frappe.db.exists("File", {"file_url": url})):
                frappe.throw("The quotation must be an existing ERPNext attachment.")
        if not (self.get("price_qty_lines") or []) or self.total_qty <= 0:
            frappe.throw("At least one proposed variant with a positive quantity is required.")
        for row in self.price_qty_lines:
            if row.proposed_qty <= 0 or row.negotiated_unit_price <= 0 or row.supplier_quoted_price <= 0:
                frappe.throw("Each variant requires positive Qty, Quoted Price and Negotiated Price.")
            if row.moq and row.proposed_qty < row.moq:
                if len((row.moq_exception_reason or "").strip()) < 10:
                    frappe.throw("MOQ exception requires a reason (at least 10 characters): " + row.variant_code)
        if self.costing_method == "Detailed" and not self.get("cost_components"):
            frappe.throw("Detailed costing requires cost component lines.")
        if not self.merchandiser:
            frappe.throw("Assign a Merchandiser to the Design Code before submitting.")

    def on_trash(self):
        if self.status not in ("Draft", "Returned"):
            frappe.throw("Only Draft or Returned Cost Breakdowns can be deleted.")
        if frappe.db.exists("Design Cost Breakdown", {"source_revision": self.name}):
            frappe.throw("This costing is referenced by a later revision.")


@frappe.whitelist()
def accessible_design_cost(design_code):
    if not design_code:
        return False
    doc = frappe.get_doc("Design Code", design_code)
    user = frappe.session.user
    return bool(_allowed_design(doc, user) and
                (_preparer(doc, user) or _buyer(user)))


@frappe.whitelist()
def current_cost_breakdown(design_code):
    if not accessible_design_cost(design_code):
        frappe.throw("No permission to read commercial costing.", frappe.PermissionError)
    records = frappe.get_list("Design Cost Breakdown",
        filters={"design_code": design_code},
        fields=["name", "status", "revision_no", "total_qty", "total_purchase_value",
                "currency", "modified"], order_by="revision_no desc",
        limit_page_length=50)
    return records
