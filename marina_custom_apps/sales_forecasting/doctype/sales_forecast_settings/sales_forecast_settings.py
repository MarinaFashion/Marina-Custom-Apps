import frappe
from frappe import _
from frappe.model.document import Document


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


class SalesForecastSettings(Document):
    def validate(self):
        self._validate_mapping_fields()

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
