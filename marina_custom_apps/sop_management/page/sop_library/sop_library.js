frappe.pages["sop-library"].on_page_load = function(wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("SOP Library"),
        single_column: true
    });

    const state = {
        language: "Bilingual",
        rows: [],
        selected: null
    };

    const body = $(`
        <style>
            .sop-library .sop-viewer { color:#2D2926; }
            .sop-library .sop-doc-head {
                border-top:6px solid #551C25;
                border-bottom:2px solid #C0A392;
                padding:14px 0 12px;
                margin-bottom:14px;
            }
            .sop-library .sop-doc-brand {
                color:#551C25;font-weight:700;font-size:20px;letter-spacing:.5px;
            }
            .sop-library .sop-meta {
                display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));
                border:1px solid var(--border-color);margin:12px 0 20px;
            }
            .sop-library .sop-meta > div { padding:8px;border-right:1px solid var(--border-color); }
            .sop-library .sop-meta .k { background:var(--subtle-fg);font-weight:600;color:#551C25; }
            .sop-library .sop-section-title {
                background:#551C25;color:white;border-left:5px solid #C0A392;
                padding:8px 10px;margin:18px 0 9px;font-weight:700;
            }
            .sop-library .sop-section-title.rtl {
                direction:rtl;text-align:right;border-left:0;border-right:5px solid #C0A392;
            }
            .sop-library .sop-rich table,.sop-library .sop-custom-content table {
                width:100% !important;border-collapse:collapse !important;margin:10px 0 15px !important;
            }
            .sop-library .sop-rich th,.sop-library .sop-rich td,.sop-library .sop-custom-content th,.sop-library .sop-custom-content td {
                border:1px solid #C0A392 !important;padding:7px 8px !important;vertical-align:top;
            }
            .sop-library .sop-rich th,.sop-library .sop-custom-content th { background:#E4D5C4 !important;color:#551C25 !important; }
            .sop-library .sop-revision { width:100%;border-collapse:collapse;margin-top:8px;font-size:12px; }
            .sop-library .sop-revision th,.sop-library .sop-revision td {
                border:1px solid var(--border-color);padding:6px;
            }
            .sop-library .sop-revision th { background:#F2EBE7;color:#551C25; }
            .sop-library .sop-tree-root {padding:12px 14px;font-weight:700;color:#551C25;background:#F2EBE7;border-bottom:1px solid #E4D5C4;}
            .sop-library .sop-type-head {display:flex;gap:7px;padding:10px 14px;cursor:pointer;font-weight:700;color:#551C25;}
            .sop-library .sop-type-head:hover,.sop-library .sop-result:hover {background:#F2EBE7;}
            .sop-library .sop-result {padding:12px 16px 12px 36px;border-top:1px solid var(--border-color);cursor:pointer;}
            @media (max-width: 900px) {
                .sop-library .sop-layout { grid-template-columns:1fr !important; }
                .sop-library .sop-filter-row { grid-template-columns:1fr 1fr !important; }
                .sop-library .sop-meta { grid-template-columns:1fr 1fr; }
            }
        </style>
        <div class="sop-library">
            <div class="sop-filter-row" style="display:grid;grid-template-columns:2fr 1fr 1fr 1fr auto;gap:10px;margin-bottom:16px;"></div>
            <div class="sop-layout" style="display:grid;grid-template-columns:minmax(280px, 36%) 1fr;gap:16px;">
                <div class="sop-results border rounded" style="min-height:520px;overflow:auto;"></div>
                <div class="sop-viewer border rounded" style="min-height:520px;padding:20px;overflow:auto;">
                    <div class="text-muted">${__("Select a published SOP to read it.")}</div>
                </div>
            </div>
        </div>
    `).appendTo(page.main);

    const filterRow = body.find(".sop-filter-row");

    const search = frappe.ui.form.make_control({
        df: { fieldtype: "Data", label: __("Search"), placeholder: __("Title, keyword, code...") },
        parent: $("<div>").appendTo(filterRow),
        render_input: true
    });
    const type = frappe.ui.form.make_control({
        df: { fieldtype: "Link", label: __("SOP Type"), options: "SOP Type" },
        parent: $("<div>").appendTo(filterRow),
        render_input: true
    });
    const department = frappe.ui.form.make_control({
        df: { fieldtype: "Link", label: __("Department"), options: "Department" },
        parent: $("<div>").appendTo(filterRow),
        render_input: true
    });
    const language = frappe.ui.form.make_control({
        df: { fieldtype: "Select", label: __("Language"), options: "\nEnglish\nArabic\nBilingual" },
        parent: $("<div>").appendTo(filterRow),
        render_input: true
    });
    const btnWrap = $("<div style='padding-top:24px'>").appendTo(filterRow);
    const refreshBtn = $(`<button class="btn btn-primary btn-sm">${__("Search")}</button>`).appendTo(btnWrap);

    [search, type, department, language].forEach(ctrl => {
        ctrl.$input && ctrl.$input.on("change", () => load());
    });
    search.$input && search.$input.on("keydown", e => {
        if (e.key === "Enter") load();
    });
    refreshBtn.on("click", () => load());

    function esc(value) {
        return frappe.utils.escape_html(value || "");
    }

    function titleFor(row) {
        if (state.language === "Arabic") return row.title_ar || row.title_en || row.name;
        if (state.language === "English") return row.title_en || row.title_ar || row.name;
        return row.title_en || row.title_ar || row.name;
    }

    function load() {
        state.language = language.get_value() || "Bilingual";
        frappe.call({
            method: "marina_custom_apps.sop_management.api.search_library",
            args: {
                search_text: search.get_value(),
                sop_type: type.get_value(),
                department: department.get_value(),
                language: language.get_value()
            },
            freeze: false,
            callback(r) {
                state.rows = r.message || [];
                renderResults();
            }
        });
    }

    function renderResults() {
        const results = body.find(".sop-results").empty();
        if (!state.rows.length) {
            results.html(`<div class="text-muted" style="padding:20px">${__("No published SOPs found.")}</div>`);
            return;
        }
        results.append(`<div class="sop-tree-root">SOP</div>`);
        const grouped = {};
        state.rows.forEach(row => {
            const key = row.sop_type || __("Other");
            (grouped[key] ||= []).push(row);
        });
        Object.keys(grouped).forEach(typeName => {
            const group = $(`<div class="sop-type-group"></div>`);
            const head = $(`<div class="sop-type-head"><span class="caret">&#9662;</span><span>${esc(typeName)}</span><span class="text-muted small">(${grouped[typeName].length})</span></div>`);
            const children = $(`<div class="sop-type-children"></div>`);
            grouped[typeName].forEach(row => {
                const card = $(`<div class="sop-result" data-name="${esc(row.name)}">
                    <div style="font-weight:700">${esc(titleFor(row))}</div>
                    <div class="text-muted small" style="margin-top:4px">${esc(row.document_no || row.name)} &middot; ${esc(row.sop_type)} &middot; v${esc(row.current_version_no)}</div>
                    <div class="small" style="margin-top:4px">${esc(row.department || "")}</div>
                </div>`);
                card.on("click", () => openSOP(row.name));
                children.append(card);
            });
            head.on("click", () => {
                const visible=children.is(":visible");
                children.toggle(!visible);
                head.find(".caret").html(visible ? "&#9656;" : "&#9662;");
            });
            group.append(head,children); results.append(group);
        });
    }

    function openSOP(name) {
        frappe.call({
            method: "marina_custom_apps.sop_management.api.get_published_sop",
            args: { sop_document: name },
            freeze: false,
            callback(r) {
                if (!r.message) return;
                state.selected = r.message;
                renderSOP();
            }
        });
    }

    function renderSOP() {
        const data = state.selected;
        const doc = data.document;
        const viewer = body.find(".sop-viewer").empty();
        const lang = state.language === "Bilingual" ? doc.language : state.language;

        const header = $(`
            <div class="sop-doc-head">
                ${lang === "Arabic"
                    ? `<div class="sop-doc-brand" dir="rtl" style="text-align:right">\u0645\u0627\u0631\u064a\u0646\u0627 \u0641\u0627\u0634\u0648\u0646 - \u062f\u0644\u064a\u0644 \u0627\u0644\u0627\u062c\u0631\u0627\u0621\u0627\u062a \u0627\u0644\u0642\u064a\u0627\u0633\u064a\u0629</div>`
                    : lang === "Bilingual"
                        ? `<div class="sop-doc-brand">Marina Fashion - SOP System</div><div class="sop-doc-brand" dir="rtl" style="text-align:right;font-size:17px">\u0645\u0627\u0631\u064a\u0646\u0627 \u0641\u0627\u0634\u0648\u0646 - \u062f\u0644\u064a\u0644 \u0627\u0644\u0627\u062c\u0631\u0627\u0621\u0627\u062a \u0627\u0644\u0642\u064a\u0627\u0633\u064a\u0629</div>`
                        : `<div class="sop-doc-brand">Marina Fashion - SOP System</div>`}                <div class="text-muted small">${esc(doc.sop_type || "Controlled Document")}</div>
                <h3 style="margin:6px 0">${esc(lang === "Arabic" ? (doc.title_ar || doc.title_en) : (doc.title_en || doc.title_ar))}</h3>
            </div>
            <div style="display:flex;gap:8px;margin-bottom:12px">
                <button class="btn btn-sm btn-primary sop-print">${__("Print / PDF")}</button>
                <button class="btn btn-sm btn-default sop-open-record">${__("Open SOP Record")}</button>
            </div>
            <div class="sop-meta">
                <div class="k">${__("Document No.")}</div><div>${esc(doc.document_no || doc.name)}</div>
                <div class="k">${__("Version")}</div><div>${esc(doc.version_no)}</div>
                <div class="k">${__("Department")}</div><div>${esc(doc.department || "")}</div>
                <div class="k">${__("Effective Date")}</div><div>${esc(doc.effective_from || "")}</div>
            </div>
        `);
        viewer.append(header);
        header.find(".sop-print").on("click", () => {
            const params = new URLSearchParams({
                doctype: "SOP Version",
                name: doc.current_version,
                format: "Marina SOP Controlled Document",
                no_letterhead: "1",
                trigger_print: "0"
            });
            window.open(`/printview?${params.toString()}`, "_blank");
        });
        header.find(".sop-open-record").on("click", () => {
            frappe.set_route("Form", "SOP Document", doc.name);
        });

        if (doc.summary) {
            viewer.append(`
                <div class="sop-section-title">${__("Document Summary")}</div>
                <div class="sop-rich">${esc(doc.summary)}</div>
            `);
        }

        if (doc.content_mode === "Advanced HTML") {
            viewer.append(`<div class="sop-custom-content">${doc.html_content || ""}</div>`);
        } else {
        data.sections.forEach(section => {
            if (lang === "Arabic") {
                viewer.append(`
                    <section dir="rtl" style="text-align:right;margin-bottom:24px">
                        <div class="sop-section-title rtl">${esc(section.section_no)} ${esc(section.heading_ar || section.heading_en)}</div>
                        <div class="sop-rich">${section.content_ar || section.content_en || ""}</div>
                    </section>
                `);
            } else if (lang === "English") {
                viewer.append(`
                    <section style="margin-bottom:24px">
                        <div class="sop-section-title">${esc(section.section_no)} ${esc(section.heading_en || section.heading_ar)}</div>
                        <div class="sop-rich">${section.content_en || section.content_ar || ""}</div>
                    </section>
                `);
            } else {
                viewer.append(`
                    <section style="margin-bottom:30px">
                        <div style="margin-bottom:14px">
                            <div class="sop-section-title">${esc(section.section_no)} ${esc(section.heading_en || "")}</div>
                            <div class="sop-rich">${section.content_en || ""}</div>
                        </div>
                        <div dir="rtl" style="text-align:right;border-top:1px solid var(--border-color);padding-top:14px">
                            <div class="sop-section-title rtl">${esc(section.section_no)} ${esc(section.heading_ar || "")}</div>
                            <div class="sop-rich">${section.content_ar || ""}</div>
                        </div>
                    </section>
                `);
            }
        });
        }

        if ((data.revision_history || []).length) {
            let rows = data.revision_history.map(row => `
                <tr>
                    <td>${esc(row.version_no)}</td>
                    <td>${esc(row.status)}</td>
                    <td>${esc(row.effective_from || "")}</td>
                    <td>${esc(row.change_summary || "")}</td>
                    <td>${esc(row.approved_by || "")}</td>
                </tr>
            `).join("");
            viewer.append(`
                <div class="sop-section-title">${__("Revision History")}</div>
                <table class="sop-revision">
                    <thead><tr>
                        <th>${__("Version")}</th>
                        <th>${__("Status")}</th>
                        <th>${__("Effective Date")}</th>
                        <th>${__("Change Summary")}</th>
                        <th>${__("Approved By")}</th>
                    </tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            `);
        }
    }

    const routeOptions = frappe.route_options || {};
    frappe.route_options = null;
    load();
    if (routeOptions.sop) {
        setTimeout(() => openSOP(routeOptions.sop), 250);
    }
};

frappe.pages["sop-library"].on_page_show = function() {
    // Page state is refreshed by the controls/search call.
};
