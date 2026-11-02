/* Module-scoped User Link titles. Persistent Link values remain User IDs.
   Only load titles for an authorized Marina document, never enumerate Users. */
(() => {
    const doctypes = [
        "Design Code", "Mood Board", "Design Document",
        "Design Milestone Execution", "Design Milestone Plan Entry",
        "Design Milestone Custody Event",
        "Design Management Settings", "Design Module Role",
        "Design Milestone Type", "Design Item Creation",
        "Production Colorway", "Design Document Type",
        "Design Module Managed Grant",
        "Design Document Assignment Removal Log",
        "Marina Pantone", "Marina Fashion Category"
    ];
    function updateLink(field, user, titles, staticArea) {
        if (!user || !titles[user] || !field) return;
        const username=titles[user];
        // Never change a Link's stored User ID or an editor's typed value.
        if (field.$input?.is(":focus")) return;
        if (typeof field.set_link_title === "function") {
            field.is_title_link = () => true;
            field.set_link_title(user);
        }
        // Read-only User links use a separate visual anchor. Frappe can
        // otherwise display User.full_name from its global title metadata.
        // Modify only that rendered label, leaving the href/ID untouched.
        if (field.df?.read_only && field.$wrapper) {
            const control=field.$wrapper.find(".control-value");
            const anchor=control.find("a");
            if(anchor.length)anchor.text(username);
            else if(control.length)control.text(username);
        }
        // Child-table inline cells are static HTML, not control inputs.
        if(staticArea){
            const anchor=staticArea.find("a");
            if(anchor.length)anchor.text(username);
            else if(staticArea.length)staticArea.text(username);
        }
    }
    function refreshTitles(frm) {
        if (frm.is_new() || !frm.doc.name) return;
        const name = frm.doc.name;
        frappe.call({
            method: "marina_custom_apps.design_management.api.user_display.document_usernames",
            args: {doctype: frm.doctype, document_name: name}
        }).then(({message}) => {
            if (frm.doc.name !== name) return;
            const titles = message || {};
            Object.entries(titles).forEach(([user, username]) => {
                if (user && username) frappe.utils.add_link_title("User", user, username);
            });
            const meta = frappe.get_meta(frm.doctype);
            (meta.fields || []).forEach(df => {
                if (df.fieldtype === "Link" && df.options === "User") {
                    updateLink(frm.fields_dict[df.fieldname], frm.doc[df.fieldname], titles);
                } else if (df.fieldtype === "Table") {
                    const grid = frm.fields_dict[df.fieldname]?.grid;
                    if (!grid) return;
                    (grid.grid_rows || []).forEach(row => {
                        const expanded=row.grid_form?.wrapper?.is(":visible");
                        const childmeta = frappe.get_meta(df.options);
                        (childmeta.fields || []).filter(f =>
                            f.fieldtype === "Link" && f.options === "User"
                        ).forEach(f => {
                            const col=row.columns?.[f.fieldname];
                            const control=expanded ?
                                row.grid_form.fields_dict?.[f.fieldname] :
                                col?.field;
                            updateLink(control, row.doc[f.fieldname], titles,
                                col?.static_area);
                        });
                    });
                }
            });
        }).catch(() => {
            // Respect denied access; do not retry with a wider User lookup.
        });
    }
    doctypes.forEach(doctype => {
        frappe.ui.form.on(doctype, {refresh: refreshTitles});
    });
})();
