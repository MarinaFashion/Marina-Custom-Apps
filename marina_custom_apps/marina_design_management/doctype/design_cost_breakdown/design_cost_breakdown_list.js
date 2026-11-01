/* Marina commercial approval overview; no client-side permission shortcuts. */
frappe.listview_settings["Design Cost Breakdown"] = {
    add_fields:["status","revision_no","design_code","currency","total_qty","total_purchase_value"],
    get_indicator(doc){
        const indicators = {
            "Draft":["Draft","gray","status,=,Draft"],
            "Pending Approval":["Pending Approval","orange","status,=,Pending Approval"],
            "Returned":["Returned","red","status,=,Returned"],
            "Approved":["Approved","green","status,=,Approved"],
            "Superseded":["Superseded","blue","status,=,Superseded"],
            "Cancelled":["Cancelled","red","status,=,Cancelled"]
        };
        return indicators[doc.status] || [doc.status||"Draft","gray",""];
    }
};
