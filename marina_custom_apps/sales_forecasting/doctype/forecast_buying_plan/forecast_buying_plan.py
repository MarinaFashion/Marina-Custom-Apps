import re
from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import flt, getdate, nowdate


class ForecastBuyingPlan(Document):
    def autoname(self):
        season = re.sub(r"[^A-Za-z0-9]+", "-", self.season or "Plan").strip("-") or "Plan"
        version = int(self.version or 1)
        self.name = make_autoname(f"FBP-{self.plan_year}-{season}-V{version:02d}-.###")

    def validate(self):
        self._set_defaults()
        self._canonicalize_item_classifications()
        self._validate_rows()
        self._calculate_plan()

    def before_submit(self):
        self.status = "Approved"
        self._calculate_plan()

    def on_submit(self):
        self._supersede_previous_versions()
        frappe.db.set_value(self.doctype, self.name, "status", "Approved", update_modified=False)

    def on_cancel(self):
        frappe.db.set_value(self.doctype, self.name, "status", "Cancelled", update_modified=False)

    def _set_defaults(self):
        settings = frappe.get_single("Sales Forecast Settings")
        if not self.company:
            self.company = settings.company or "Marina"
        if not self.currency:
            self.currency = settings.currency or "SAR"
        if not self.effective_from:
            self.effective_from = nowdate()
        if not self.version:
            self.version = 1
        if self.docstatus == 0:
            self.status = "Draft"


    def _canonicalize_item_classifications(self):
        settings = frappe.get_single("Sales Forecast Settings")
        meta = frappe.get_meta("Item")

        def canonical(fieldname, value):
            if not value:
                return value
            df = meta.get_field(fieldname)
            if not df or not df.options or df.fieldtype != "Select":
                return value.strip() if isinstance(value, str) else value
            options = [x.strip() for x in str(df.options).split("\n") if x.strip()]
            token = re.sub(r"[^a-z0-9]+", "", str(value).lower())
            for option in options:
                if re.sub(r"[^a-z0-9]+", "", option.lower()) == token:
                    return option
            return value.strip() if isinstance(value, str) else value

        self.season = canonical(settings.item_season_field or "season", self.season)
        for row in self.items:
            row.collection = canonical(settings.item_collection_field or "collection", row.collection)
            row.drop = canonical(settings.item_drop_field or "custom_drop", row.drop)
            row.main_group = canonical(settings.item_main_group_field or "custom_item_main_group", row.main_group)

    def _validate_rows(self):
        if not self.items:
            frappe.throw(_("Add at least one buying-plan row."))

        seen = set()
        for row in self.items:
            key = (
                (row.collection or "").strip(),
                (row.drop or "").strip(),
                str(row.display_date or ""),
                (row.main_group or "").strip(),
            )
            if key in seen:
                frappe.throw(
                    _("Duplicate buying-plan row: {0} / {1} / {2} / {3}").format(*key)
                )
            seen.add(key)

            if row.display_date and int(getdate(row.display_date).year) not in (
                int(self.plan_year or 0) - 1,
                int(self.plan_year or 0),
                int(self.plan_year or 0) + 1,
            ):
                frappe.throw(
                    _("Display Date {0} looks inconsistent with plan year {1}.").format(
                        row.display_date, self.plan_year
                    )
                )

            if flt(row.planned_styles) < 0 or flt(row.planned_total_qty) < 0:
                frappe.throw(_("Styles and Total Qty cannot be negative."))
            if flt(row.planned_total_cost) < 0 or flt(row.planned_selling_value) < 0:
                frappe.throw(_("Cost and selling value cannot be negative."))

    def _calculate_plan(self):
        settings = frappe.get_single("Sales Forecast Settings")
        vat_rate = flt(settings.vat_rate or 15)
        vat_factor = 1 + (vat_rate / 100.0)

        totals = {
            "styles": 0.0,
            "qty": 0.0,
            "cost": 0.0,
            "selling": 0.0,
            "ex_vat": 0.0,
            "profit": 0.0,
            "styles_created": 0.0,
            "styles_priced": 0.0,
            "po_qty": 0.0,
            "received_qty": 0.0,
        }
        group_totals = defaultdict(
            lambda: {
                "styles": 0.0,
                "qty": 0.0,
                "styles_created": 0.0,
                "po_qty": 0.0,
                "received_qty": 0.0,
            }
        )

        for row in self.items:
            styles = flt(row.planned_styles)
            qty = flt(row.planned_total_qty)
            cost = flt(row.planned_total_cost)
            selling = flt(row.planned_selling_value)
            ex_vat = selling / vat_factor if vat_factor else selling
            profit = ex_vat - cost

            row.avg_qty_per_style = qty / styles if styles else 0
            row.avg_cost_per_unit = cost / qty if qty else 0
            row.planned_asp = selling / qty if qty else 0
            row.selling_value_ex_vat = ex_vat
            row.planned_gross_profit = profit
            row.planned_margin_pct = (profit / ex_vat * 100) if ex_vat else 0

            row.assortment_readiness_pct = min(100, flt(row.styles_created) / styles * 100) if styles else 0
            row.price_readiness_pct = min(100, flt(row.styles_priced) / max(flt(row.styles_created), 1) * 100) if flt(row.styles_created) else 0
            row.po_completion_pct = min(100, flt(row.po_qty) / qty * 100) if qty else 0
            row.receipt_completion_pct = min(100, flt(row.received_qty) / qty * 100) if qty else 0

            totals["styles"] += styles
            totals["qty"] += qty
            totals["cost"] += cost
            totals["selling"] += selling
            totals["ex_vat"] += ex_vat
            totals["profit"] += profit
            totals["styles_created"] += flt(row.styles_created)
            totals["styles_priced"] += flt(row.styles_priced)
            totals["po_qty"] += flt(row.po_qty)
            totals["received_qty"] += flt(row.received_qty)

            group = (row.main_group or "").strip()
            group_totals[group]["styles"] += styles
            group_totals[group]["qty"] += qty
            group_totals[group]["styles_created"] += flt(row.styles_created)
            group_totals[group]["po_qty"] += flt(row.po_qty)
            group_totals[group]["received_qty"] += flt(row.received_qty)

        capped_styles_created = sum(
            min(values["styles_created"], values["styles"])
            for values in group_totals.values()
        )
        capped_po_qty = sum(
            min(values["po_qty"], values["qty"])
            for values in group_totals.values()
        )
        capped_received_qty = sum(
            min(values["received_qty"], values["qty"])
            for values in group_totals.values()
        )

        self.total_styles = int(totals["styles"])
        self.total_qty = totals["qty"]
        self.total_cost = totals["cost"]
        self.total_selling_value = totals["selling"]
        self.selling_value_ex_vat = totals["ex_vat"]
        self.planned_gross_profit = totals["profit"]
        self.planned_margin_pct = (
            totals["profit"] / totals["ex_vat"] * 100 if totals["ex_vat"] else 0
        )
        self.styles_created = int(totals["styles_created"])
        self.styles_priced = int(totals["styles_priced"])
        self.po_qty = totals["po_qty"]
        self.received_qty = totals["received_qty"]
        self.assortment_readiness_pct = (
            capped_styles_created / totals["styles"] * 100
            if totals["styles"]
            else 0
        )
        self.po_completion_pct = (
            capped_po_qty / totals["qty"] * 100 if totals["qty"] else 0
        )
        self.receipt_completion_pct = (
            capped_received_qty / totals["qty"] * 100
            if totals["qty"]
            else 0
        )

    def _supersede_previous_versions(self):
        previous = frappe.get_all(
            self.doctype,
            filters={
                "name": ["!=", self.name],
                "company": self.company,
                "plan_year": self.plan_year,
                "season": self.season,
                "docstatus": 1,
                "status": "Approved",
            },
            pluck="name",
        )
        for name in previous:
            frappe.db.set_value(self.doctype, name, "status", "Superseded", update_modified=False)
