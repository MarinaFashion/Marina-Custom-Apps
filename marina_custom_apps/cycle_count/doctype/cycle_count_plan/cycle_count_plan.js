frappe.ui.form.on("Cycle Count Plan", {
  refresh(frm) {
    if (frm.doc.docstatus !== 0) return;
    if (frm.doc.selection_mode === "Item Group" && frm.doc.item_group) {
      frm.add_custom_button(__("Load Styles from Item Group"), () => frm.call("load_styles").then(() => frm.reload_doc()));
    }
    if (frm.doc.name && frm.doc.styles?.length && frm.doc.stores?.length) {
      frm.add_custom_button(__("Generate Store Counts"), () => {
        frappe.confirm(__("Generate one Store Cycle Count for each selected store?"),
          () => frm.call("generate_store_counts").then(() => frm.reload_doc()));
      }, __("Actions"));
    }
  }
});
