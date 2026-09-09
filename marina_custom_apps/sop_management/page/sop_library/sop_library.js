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
        state.rows.forEach(row => {
            const card = $(`
                <div class="sop-result" data-name="${esc(row.name)}"
                    style="padding:14px 16px;border-bottom:1px solid var(--border-color);cursor:pointer;">
                    <div style="font-weight:600">${esc(titleFor(row))}</div>
                    <div class="text-muted small" style="margin-top:4px">
                        ${esc(row.name)} · ${esc(row.sop_type)} · v${esc(row.current_version_no)}
                    </div>
                    <div class="small" style="margin-top:4px">${esc(row.department || "")}</div>
                </div>
            `);
            card.on("click", () => openSOP(row.name));
            results.append(card);
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
            <div style="margin-bottom:20px">
                <div class="text-muted small">${esc(doc.name)} · ${esc(doc.sop_type)} · v${esc(doc.version_no)}</div>
                <h3 style="margin:6px 0">${esc(lang === "Arabic" ? (doc.title_ar || doc.title_en) : (doc.title_en || doc.title_ar))}</h3>
                <div class="text-muted small">${esc(doc.department || "")} ${doc.effective_from ? " · " + esc(doc.effective_from) : ""}</div>
            </div>
        `);
        viewer.append(header);

        data.sections.forEach(section => {
            if (lang === "Arabic") {
                viewer.append(`
                    <section dir="rtl" style="text-align:right;margin-bottom:24px">
                        <h5>${esc(section.section_no)} ${esc(section.heading_ar || section.heading_en)}</h5>
                        <div>${section.content_ar || section.content_en || ""}</div>
                    </section>
                `);
            } else if (lang === "English") {
                viewer.append(`
                    <section style="margin-bottom:24px">
                        <h5>${esc(section.section_no)} ${esc(section.heading_en || section.heading_ar)}</h5>
                        <div>${section.content_en || section.content_ar || ""}</div>
                    </section>
                `);
            } else {
                viewer.append(`
                    <section style="margin-bottom:30px">
                        <div style="margin-bottom:14px">
                            <h5>${esc(section.section_no)} ${esc(section.heading_en || "")}</h5>
                            <div>${section.content_en || ""}</div>
                        </div>
                        <div dir="rtl" style="text-align:right;border-top:1px solid var(--border-color);padding-top:14px">
                            <h5>${esc(section.section_no)} ${esc(section.heading_ar || "")}</h5>
                            <div>${section.content_ar || ""}</div>
                        </div>
                    </section>
                `);
            }
        });
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
