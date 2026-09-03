const FIELD_MAPPINGS = {
    Branch: [
        "branch_company_field",
        "branch_opening_date_field",
        "branch_store_space_field",
        "branch_cluster_field",
        "branch_warehouse_field",
        "branch_pos_profile_field",
        "branch_city_field"
    ],
    Item: [
        "item_main_group_field",
        "item_sub_group_field",
        "item_year_field",
        "item_season_field",
        "item_collection_field",
        "item_drop_field",
        "item_display_date_field"
    ]
};

const NON_DATA_FIELD_TYPES = new Set([
    "Section Break",
    "Column Break",
    "Tab Break",
    "HTML",
    "Button",
    "Table",
    "Table MultiSelect",
    "Fold",
    "Heading",
    "Image"
]);

frappe.ui.form.on("Sales Forecast Settings", {
    refresh(frm) {
        load_field_mapping_options(frm);
    }
});

function load_field_mapping_options(frm) {
    Object.entries(FIELD_MAPPINGS).forEach(([doctype, setting_fields]) => {
        frappe.model.with_doctype(doctype, () => {
            const meta = frappe.get_meta(doctype);
            const options = [
                {
                    label: __("Document Name (name)"),
                    value: "name",
                    description: __("Standard document name")
                },
                ...(meta.fields || [])
                    .filter(df => df.fieldname && !NON_DATA_FIELD_TYPES.has(df.fieldtype))
                    .map(df => ({
                        label: `${__(df.label || df.fieldname)} (${df.fieldname})`,
                        value: df.fieldname,
                        description: df.options
                            ? `${df.fieldtype} → ${df.options}`
                            : df.fieldtype
                    }))
            ];

            setting_fields.forEach(fieldname => {
                const control = frm.fields_dict[fieldname];
                if (!control || typeof control.set_data !== "function") return;

                control.set_data(options);
                if (frm.doc[fieldname]) {
                    control.set_input(frm.doc[fieldname]);
                }
            });
        });
    });
}
