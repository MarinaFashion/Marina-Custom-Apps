frappe.query_reports["Users Available per Module"] = {
  filters: [
    {
      fieldname: "module",
      label: __("Module"),
      fieldtype: "Link",
      options: "Module Def",
    },
    {
      fieldname: "only_with_blocks",
      label: __("Only Modules With Blocked Users"),
      fieldtype: "Check",
      default: 0,
    },
  ],
};
