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
        {fieldname:"report_currency", label:__("Currency"), fieldtype:"Select", options:"CNY\nSAR", default:"CNY", reqd:1},
        {fieldname:"tolerance_pct", label:__("Tolerance %"), fieldtype:"Percent", default:8, reqd:1},
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
       /* Marina Fashion visual identity, scoped entirely to this report. */
       .marina-po-matrix {
           --marina-primary:#551C25; --marina-cream:#F2EBE7;
           --marina-taupe:#C0A392; --marina-sand:#E4D5C4;
           --marina-charcoal:#2D2926;
           padding:12px 0 24px;color:var(--marina-charcoal);
       }
       .marina-po-matrix .matrix-scroll {
           overflow:auto;max-height:calc(100vh - 275px);
           border:1px solid var(--marina-taupe);border-radius:6px;
       }
       .marina-po-matrix table {border-collapse:separate;border-spacing:0;min-width:850px;width:100%;font-size:12px;}
       .marina-po-matrix td,.marina-po-matrix th {
           border-right:1px solid var(--marina-sand);
           border-bottom:1px solid var(--marina-sand);
           padding:5px 8px;white-space:nowrap;
       }
       .marina-po-matrix thead th {
           background:var(--marina-primary);color:#fff;position:sticky;top:0;
           z-index:3;text-align:center;font-weight:700;
       }
       .marina-po-matrix td.number {text-align:right;font-variant-numeric:tabular-nums;}
       .marina-po-matrix td.label {font-weight:600;background:var(--marina-cream);}
       .marina-po-matrix tr:nth-child(even) td.label,
       .marina-po-matrix tr:nth-child(even) td.number {background:#faf6f3;}
       .marina-po-matrix tr.variance td.label,
       .marina-po-matrix tr.variance td.number {
           background:var(--marina-sand)!important;color:var(--marina-primary);font-weight:700;
       }
       .marina-po-matrix tr.discount td.label,
       .marina-po-matrix tr.discount td.number {background:var(--marina-cream);font-weight:700;}
       .marina-po-matrix tr.discount td.number,
       .marina-po-matrix tr.excess td.total {color:var(--marina-primary);font-weight:800;}
       .marina-po-matrix td.identity {
           background:#fff!important;vertical-align:middle;text-align:center;font-weight:700;
           border-left:3px solid var(--marina-primary);
       }
       .marina-po-matrix td.identity {color:var(--marina-primary);}
       .marina-po-matrix td.photo {background:#fff!important;vertical-align:middle;text-align:center;}
       .marina-po-matrix td.photo img {max-width:120px;max-height:145px;object-fit:contain;}
       .marina-po-matrix td.total {background:var(--marina-sand)!important;font-weight:700;}
       /* Strong outer outline around each 8-row item block; no double lines. */
       .marina-po-matrix tbody tr.item-start > td:not(.identity):not(.photo) {
           border-top:3px solid var(--marina-primary);
       }
       .marina-po-matrix tbody tr.item-end > td {
           border-bottom:3px solid var(--marina-primary);
       }
       .marina-po-matrix tbody td.identity,
       .marina-po-matrix tbody td.photo {
           border-top:3px solid var(--marina-primary);
           border-bottom:3px solid var(--marina-primary);
       }
       .marina-po-matrix tbody tr > td:last-child {
           border-right:3px solid var(--marina-primary);
       }
       .marina-po-matrix .hint {padding:9px 0;color:var(--marina-primary);font-weight:500;}
       .marina-po-matrix .grand-totals {display:flex;flex-wrap:wrap;gap:12px;margin:12px 0 15px;}
       .marina-po-matrix .grand-total {flex:1;min-width:195px;background:var(--marina-cream);
           border:1px solid var(--marina-sand);border-left:4px solid var(--marina-primary);
           border-radius:5px;padding:12px 16px;}
       .marina-po-matrix .grand-total .caption {font-size:12px;color:var(--marina-charcoal);font-weight:500;}
       .marina-po-matrix .grand-total .value {font-size:20px;font-weight:800;color:var(--marina-primary);}
       .marina-po-matrix .grand-total.final {background:var(--marina-primary);}
       .marina-po-matrix .grand-total.final .caption,
       .marina-po-matrix .grand-total.final .value {color:#fff;}
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
        ["tolerance_qty", __("Accept Qty"), 0],
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
        metrics[4][1] = __("Accept Qty ({0}%)", [fmt(data.tolerance_pct, 2).replace(/\.00$/, "")]);
        metrics[6][1] = __("Unit Cost ({0})", [data.currency]);
        metrics[7][1] = __("Discount Amount ({0})", [data.currency]);
        let html = '<div class="hint">' + esc(__("Tolerance: {0}% per Item Variant (rounded to whole units). Template totals aggregate variant-level results.", [fmt(data.tolerance_pct, 2).replace(/\.00$/, "")])) +
            ' · ' + esc(__("Currency")) + ': ' + esc(data.currency) + '</div>';
        const grand = data.grand_totals || {};
        const summary = [
            [__("Total Eligible Extra Qty"), fmt(grand.eligible_excess_qty, 0), false],
            [__("Amount Before Discount ({0})", [data.currency]), fmt(grand.eligible_amount_before_discount, 2), false],
            [__("Discount Amount ({0})", [data.currency]), fmt(grand.discount_value, 2), true]
        ];
        html += '<div class="grand-totals">' + summary.map(([label,value,final]) =>
            '<div class="grand-total' + (final ? ' final' : '') + '">' +
            '<div class="caption">' + esc(label) + '</div><div class="value">' +
            esc(value) + '</div></div>').join('') + '</div>';
        html += '<div class="matrix-scroll"><table><thead><tr><th>' + esc(__("Item Code")) +
            '</th><th>' + esc(__("Image")) + '</th><th>' + esc(__("Values")) + '</th>' +
            sizes.map(s => '<th>' + esc(s) + '</th>').join('') + '<th>' + esc(__("Total")) + '</th></tr></thead><tbody>';
        blocks.forEach(block => {
            const variants = new Map(block.variants.map(v => [v.label,v]));
            metrics.forEach(([key,label,digits], i) => {
                let cls = key === "variance_qty" ? "variance" : key === "discount_value" ? "discount" :
                    key === "eligible_excess_qty" ? "excess" : "";
                cls += (i === 0 ? " item-start" : "") + (i === metrics.length - 1 ? " item-end" : "");
                html += '<tr class="' + cls + '">';
                if (i === 0) {
                    html += '<td class="identity" rowspan="' + metrics.length + '">' +
                        esc(block.item_code) + '</td>';
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
            const value = controls[f.fieldname].get_value();
            args[f.fieldname] = (value === null || value === undefined) ? "" : value;
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
        const sizes = $root.find("thead th").slice(3,-1).map(function() {
            return $(this).text().trim();
        }).get();
        const grand = current.grand_totals || {};
        const lines = [
            ["Report Currency", current.currency],
            ["Total Eligible Extra Qty", grand.eligible_excess_qty],
            ["Amount Before Discount", grand.eligible_amount_before_discount],
            ["Discount Amount", grand.discount_value],
            [],
            ["Item Code","Image","Values",...sizes,"Total"]
        ];
        current.blocks.forEach(block => {
            const variants = new Map(block.variants.map(v => [v.label,v]));
            metrics.forEach(([key,label,digits],index) => {
                const cell = v => v == null ? "" : fmt(v,digits) +
                    (key === "variance_pct" ? "%" : "");
                lines.push([
                    index === 0 ? block.item_code : "",
                    index === 0 ? (block.image || "") : "",
                    label,
                    ...sizes.map(size => variants.has(size) ?
                        cell(variants.get(size)[key]) : ""),
                    cell(block.totals[key])
                ]);
            });
        });
        const grid = lines.map(cells => cells.map(value =>
            '"' + String(value).replace(/"/g,'""') + '"').join(",")).join("\r\n");
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
