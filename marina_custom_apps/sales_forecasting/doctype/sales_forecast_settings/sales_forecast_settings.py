import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


MAPPING_FIELDS = {
    "Branch": (
        "branch_company_field",
        "branch_opening_date_field",
        "branch_store_space_field",
        "branch_cluster_field",
        "branch_warehouse_field",
        "branch_pos_profile_field",
        "branch_city_field",
    ),
    "Item": (
        "item_main_group_field",
        "item_sub_group_field",
        "item_year_field",
        "item_season_field",
        "item_collection_field",
        "item_drop_field",
        "item_display_date_field",
    ),
}

NON_DATA_FIELD_TYPES = {
    "Section Break",
    "Column Break",
    "Tab Break",
    "HTML",
    "Button",
    "Table",
    "Table MultiSelect",
    "Fold",
    "Heading",
    "Image",
}

DAY_FIELDS = (
    "salary_pre_start_day",
    "salary_peak_start_day",
    "salary_peak_end_next_month_day",
    "salary_decline_end_day",
)

POSITIVE_FIELDS = (
    "displayed_style_window_days",
    "inventory_active_window_days",
    "ignore_pos_shift_over_hours",
    "data_mart_batch_size",
    "lookback_years",
    "recency_half_life_days",
    "minimum_analog_samples",
    "confidence_z",
)


class SalesForecastSettings(Document):
    def validate(self):
        self._validate_mapping_fields()
        self._validate_ranges()

    def _validate_mapping_fields(self):
        for doctype, setting_fields in MAPPING_FIELDS.items():
            meta = frappe.get_meta(doctype)
            valid = {
                df.fieldname
                for df in meta.fields
                if df.fieldname and df.fieldtype not in NON_DATA_FIELD_TYPES
            }
            valid.add("name")

            for setting_field in setting_fields:
                value = (self.get(setting_field) or "").strip()
                if not value:
                    frappe.throw(
                        _("{0} is required. Select a field from {1}.").format(
                            self.meta.get_label(setting_field), doctype
                        )
                    )
                if value not in valid:
                    frappe.throw(
                        _("{0}: field {1} does not exist on {2}. Please select it from the dropdown.").format(
                            self.meta.get_label(setting_field),
                            frappe.bold(value),
                            frappe.bold(doctype),
                        )
                    )

    def _validate_ranges(self):
        groups = []
        seen = set()
        for value in str(self.main_groups or "").split(","):
            value = value.strip()
            if value and value not in seen:
                groups.append(value)
                seen.add(value)
        if not groups:
            frappe.throw(_("Configure at least one Forecast Main Group."))
        self.main_groups = ",".join(groups)

        vat = flt(self.vat_rate)
        if vat < 0 or vat > 100:
            frappe.throw(_("VAT Rate must be between 0 and 100."))

        for fieldname in DAY_FIELDS:
            value = cint(self.get(fieldname))
            if value < 1 or value > 31:
                frappe.throw(
                    _("{0} must be between 1 and 31.").format(self.meta.get_label(fieldname))
                )

        for fieldname in POSITIVE_FIELDS:
            if flt(self.get(fieldname)) <= 0:
                frappe.throw(
                    _("{0} must be greater than zero.").format(self.meta.get_label(fieldname))
                )
