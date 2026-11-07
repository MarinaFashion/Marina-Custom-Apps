frappe.pages["po-receipt-variance-matrix"].on_page_load = function(wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper, title: __("PO Receipt Variance Matrix"), single_column: true
    });
    const esc = value => frappe.utils.escape_html(String(value ?? ""));
    const fmt = (v, digits=0) => {
        if (v === null || v === undefined) return "";
        return Number(v).toLocaleString(undefined, {minimumFractionDigits: digits, maximumFractionDigits: digits});
    };
    const fields = [
        {fieldname:"company", label:__("Company"), fieldtype:"Link", options:"Company", reqd:1,
         default:frappe.defaults.get_user_default("Company")},
        {fieldname:"supplier", label:__("Supplier"), fieldtype:"Link", options:"Supplier", reqd:1,
         default:"MIDMAK CNY"},
        {fieldname:"item_year", label:__("Year"), fieldtype:"Data"},
        {fieldname:"season", label:__("Season"), fieldtype:"Data"},
        {fieldname:"collection", label:__("Collection"), fieldtype:"Data"},
        {fieldname:"discount_pct", label:__("Excess Discount %"), fieldtype:"Percent", default:50, reqd:1}
    ];
    const controls = {};
    fields.forEach(f => {
        controls[f.fieldname] = page.add_field({
            ...f, change: () => {}
        });
    });
    const $root = $('<div class="marina-po-matrix"></div>').appendTo(page.main);
    const style = `<style>
       .marina-po-matrix {padding:12px 0 24px;}
       .marina-po-matrix .matrix-scroll {overflow:auto;max-height:calc(100vh - 275px);border:1px solid #ccd5da;}
       .marina-po-matrix table {border-collapse:collapse;min-width:850px;width:100%;font-size:12px;}
       .marina-po-matrix td,.marina-po-matrix th {border:1px solid #8b969e;padding:5px 8px;white-space:nowrap;}
       .marina-po-matrix thead th {background:#bce0ef;position:sticky;top:0;z-index:3;text-align:center;}
       .marina-po-matrix td.number {text-align:right;font-variant-numeric:tabular-nums;}
       .marina-po-matrix td.label {font-weight:500;background:#e8f2f9;}
       .marina-po-matrix tr:nth-child(even) td.label,.marina-po-matrix tr:nth-child(even) td.number {background:#dcebf8;}
       .marina-po-matrix tr.variance td {background:#83cce5!important;font-weight:600;}
       .marina-po-matrix tr.discount td.number,.marina-po-matrix tr.excess td.total {color:#c81727;font-weight:700;}
       .marina-po-matrix td.identity {background:white!important;vertical-align:middle;text-align:center;font-weight:700;}
       .marina-po-matrix td.photo {background:white!important;vertical-align:middle;text-align:center;}
       .marina-po-matrix td.photo img {max-width:120px;max-height:145px;object-fit:contain;}
       .marina-po-matrix td.total {background:#dcebf8;font-weight:700;}
       .marina-po-matrix .hint {padding:9px 0;color:var(--text-muted);}
       @media print {
          .layout-main-section .page-form,.page-head,.navbar,.sidebar {display:none!important;}
          .marina-po-matrix .matrix-scroll {max-height:none;overflow:visible;}
          .marina-po-matrix thead th {position:static;}
       }
    </style>`;
    $root.before(style);
    let current = null;
    const metrics = [
        ["receipt_qty", __("Inv Qty"), 0],
        ["po_qty", __("PO Qty"), 0],
        ["variance_qty", __("Qty Diff"), 0],
        ["variance_pct", __("Diff %"), 1],
        ["tolerance_qty", __("Accept Qty (8%)"), 0],
        ["eligible_excess_qty", __("Extra Qty"), 0],
        ["unit_cost", __("Unit Cost"), 2],
        ["discount_value", __("Discount Amount"), 2]
    ];
    function render(data) {
        current = data;
        const blocks = data.blocks || [];
        if (!blocks.length) {
            $root.html('<div class="text-muted text-center" style="padding:30px">' +
                __("No submitted purchase orders match these filters.") + '</div>');
            return;
        }
        // One common size header, with all encountered size labels. Different templates
        // may have different sizes; a missing size remains blank rather than zero.
        const known = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL", "3XL", "4XL", "5XL"];
        const sizes = Array.from(new Set(blocks.flatMap(b => b.variants.map(v => v.label))));
        sizes.sort((a,b) => {
            const ai = known.indexOf(a.toUpperCase()), bi = known.indexOf(b.toUpperCase());
            if (ai !== -1 && bi !== -1) return ai-bi;
            if (ai !== -1) return -1;
            if (bi !== -1) return 1;
            return a.localeCompare(b,undefined,{numeric:true});
        });
        let html = '<div class="hint">' + esc(__("Tolerance is fixed at 8% of each item variant PO quantity, rounded to whole units. All template totals sum independently calculated variants.")) +
            ' · ' + esc(__("Currency")) + ': ' + esc(data.currency) + '</div>';
        html += '<div class="matrix-scroll"><table><thead><tr><th>' + esc(__("Item Code")) +
            '</th><th>' + esc(__("Image")) + '</th><th>' + esc(__("Values")) + '</th>' +
            sizes.map(s => '<th>' + esc(s) + '</th>').join('') + '<th>' + esc(__("Total")) + '</th></tr></thead><tbody>';
        blocks.forEach(block => {
            const variants = new Map(block.variants.map(v => [v.label,v]));
            metrics.forEach(([key,label,digits], i) => {
                let cls = key === "variance_qty" ? "variance" : key === "discount_value" ? "discount" :
                    key === "eligible_excess_qty" ? "excess" : "";
                html += '<tr class="' + cls + '">';
                if (i === 0) {
                    html += '<td class="identity" rowspan="' + metrics.length + '">' +
                        '<a href="/app/item/' + encodeURIComponent(block.item_code) + '">' +
                        esc(block.item_code) + '</a></td>';
                    const img = block.image ?
                        '<img loading="lazy" alt="" src="' + esc(block.image) + '">' :
                        '<span class="text-muted">' + esc(__("No image")) + '</span>';
                    html += '<td class="photo" rowspan="' + metrics.length + '">' + img + '</td>';
                }
                html += '<td class="label">' + esc(label) + '</td>';
                sizes.forEach(size => {
                    const row = variants.get(size);
                    html += '<td class="number"' + (row ? ' title="' + esc(row.item_code) + '"' : '') + '>' +
                        (row ? fmt(row[key],digits) + (key === "variance_pct" ? "%" : "") : "") + '</td>';
                });
                html += '<td class="number total">' + fmt(block.totals[key],digits) +
                    (key === "variance_pct" ? "%" : "") + '</td></tr>';
            });
        });
        html += '</tbody></table></div>';
        $root.html(html);
    }
    async function refresh() {
        const args = {};
        for (const f of fields) {
            args[f.fieldname] = controls[f.fieldname].get_value() || "";
            if (f.reqd && args[f.fieldname] === "") {
                frappe.msgprint(__("{0} is required", [f.label]));
                return;
            }
        }
        const result = await frappe.call({
            method:"marina_custom_apps.purchasing.po_receipt_variance_service.get_matrix_data",
            args, freeze:true, freeze_message:__("Loading variant matrix...")
        });
        render(result.message || {});
    }
    function export_csv() {
        if (!current || !current.blocks?.length) return;
        // Excel-readable export keeps the exact visual row/column arrangement.
        const grid = $root.find("table tr").map(function() {
            let cells = [];
            $(this).children("th,td").each(function() {
                const span = Number($(this).attr("rowspan") || 1);
                const value = $(this).hasClass("photo") ? "" : $(this).text().trim();
                cells.push('"' + value.replace(/"/g,'""') + '"');
            });
            return cells.join(",");
        }).get().join("\r\n");
        const blob = new Blob(["\uFEFF",grid],{type:"text/csv;charset=utf-8;"});
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url; a.download = "po_receipt_variance_matrix.csv";
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
    }
    page.set_primary_action(__("Refresh"), refresh);
    page.add_menu_item(__("Export CSV"), export_csv);
    page.add_menu_item(__("Print"), () => window.print());
    page.add_menu_item(__("Standard Report"), () => frappe.set_route("query-report","PO Receipt Variance Discount"));
    // Read initial filters passed by the standard report.
    const saved = frappe.route_options || {};
    for (const f of fields) if (saved[f.fieldname] !== undefined) controls[f.fieldname].set_value(saved[f.fieldname]);
    frappe.route_options = null;
    refresh();
};
