frappe.views.calendar["Marina Calendar Event"] = {
    field_map: {
        start: "start_date",
        end: "end_date",
        id: "name",
        allDay: "all_day",
        title: "event_name"
    },
    fields: [
        "name",
        "start_date",
        "end_date",
        "event_name",
        "all_day",
        "event_type",
        "importance",
        "expected_sales_impact",
        "impact_strength",
        "store_trading_status",
        "forecast_relevant",
        "scope",
        "company",
        "city",
        "branch",
        "main_group",
        "disabled"
    ],
    get_events_method: "marina_custom_apps.marina_calendar.api.get_calendar_events",
    get_css_class(data) {
        if (data.store_trading_status === "Closed") return "danger";
        if (data.expected_sales_impact === "Negative") return "danger";
        if (data.expected_sales_impact === "Positive") return "success";
        if (data.expected_sales_impact === "Unknown") return "warning";
        return "default";
    },
    options: {
        editable: false,
        selectable: false,
        displayEventTime: false
    }
};
