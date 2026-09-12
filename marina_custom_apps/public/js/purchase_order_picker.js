(() => {
	const QUERY =
		"marina_custom_apps.purchase_order_picker.search_purchase_orders";
	const TARGET_DOCTYPES = ["Purchase Receipt", "Purchase Invoice"];

	function install_purchase_order_picker() {
		if (
			!window.erpnext?.utils?.map_current_doc ||
			!frappe.ui?.form?.MultiSelectDialog
		) {
			return;
		}

		if (!erpnext.utils.map_current_doc.__marina_po_picker) {
			const original_map_current_doc = erpnext.utils.map_current_doc;

			const marina_map_current_doc = function (opts) {
				const target_doctype =
					opts?.target?.doc?.doctype || cur_frm?.doc?.doctype;

				if (
					opts?.source_doctype === "Purchase Order" &&
					TARGET_DOCTYPES.includes(target_doctype)
				) {
					opts = {
						...opts,
						get_query_method: QUERY,
					};
				}

				return original_map_current_doc.call(this, opts);
			};

			marina_map_current_doc.__marina_po_picker = true;
			erpnext.utils.map_current_doc = marina_map_current_doc;
		}

		if (!frappe.ui.form.MultiSelectDialog.__marina_po_picker) {
			const StandardMultiSelectDialog =
				frappe.ui.form.MultiSelectDialog;

			class MarinaMultiSelectDialog extends StandardMultiSelectDialog {
				constructor(opts) {
					let enhanced_opts = opts;

					if (opts?.doctype === "Purchase Order" && opts?.get_query) {
						let query_method = "";
						try {
							query_method = opts.get_query()?.query || "";
						} catch (e) {
							query_method = "";
						}

						if (query_method === QUERY) {
							enhanced_opts = {
								...opts,
								columns: [
									"name",
									"title",
									"supplier",
									"schedule_date",
								],
							};
						}
					}

					super(enhanced_opts);
				}
			}

			MarinaMultiSelectDialog.__marina_po_picker = true;
			frappe.ui.form.MultiSelectDialog = MarinaMultiSelectDialog;
		}
	}

	TARGET_DOCTYPES.forEach((doctype) => {
		frappe.ui.form.on(doctype, {
			setup() {
				install_purchase_order_picker();
			},
			refresh() {
				install_purchase_order_picker();
			},
		});
	});
})();