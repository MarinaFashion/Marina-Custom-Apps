frappe.query_reports["User Module Access Summary"] = {
  filters: [
    {
      fieldname: "user",
      label: __("User"),
      fieldtype: "Link",
      options: "User",
      get_query: () => ({
        filters: {
          enabled: 1,
          user_type: "System User",
          name: ["not in", ["Administrator", "Guest"]],
        },
      }),
    },
    {
      fieldname: "module_profile",
      label: __("Module Profile"),
      fieldtype: "Link",
      options: "Module Profile",
    },
    {
      fieldname: "only_with_blocks",
      label: __("Only Users With Blocked Modules"),
      fieldtype: "Check",
      default: 0,
    },
  ],
};
