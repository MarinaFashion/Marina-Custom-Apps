frappe.pages["marina-permission-manager"].on_page_load = (wrapper) => {
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: __("Permission Manager"),
    single_column: true,
  });

  frappe.breadcrumbs.add("Setup");
  wrapper.permission_manager = new MarinaPermissionManager(page);
};

class MarinaPermissionManager {
  constructor(page) {
    this.page = page;
    this.rights = [
      "select",
      "read",
      "write",
      "create",
      "delete",
      "submit",
      "cancel",
      "amend",
      "report",
      "import",
      "export",
      "print",
      "email",
      "share",
    ];
    this.rows = [];
    this.initial_rights = new Map();
    this.pending = new Set();
    this.current_role = null;
    this.groups = [];

    this.make_controls();
    this.make_body();
    this.bind_events();
    this.show_empty(__("Select a Role to load its complete permission matrix."));
  }

  make_controls() {
    this.role_field = this.page.add_field({
      fieldname: "role",
      label: __("Role"),
      fieldtype: "Link",
      options: "Role",
      reqd: 1,
      get_query: () => ({ filters: { disabled: 0, name: ["!=", "Administrator"] } }),
      change: () => this.handle_role_change(),
    });

    this.application_field = this.page.add_field({
      fieldname: "application",
      label: __("Application"),
      fieldtype: "Select",
      options: [""],
      change: () => this.handle_application_change(),
    });

    this.module_field = this.page.add_field({
      fieldname: "module",
      label: __("Module"),
      fieldtype: "Select",
      options: [""],
      change: () => this.render(),
    });

    this.status_field = this.page.add_field({
      fieldname: "status",
      label: __("Status"),
      fieldtype: "Select",
      options: ["", "Configured", "Unconfigured", "Modified"],
      change: () => this.render(),
    });

    this.search_field = this.page.add_field({
      fieldname: "search",
      label: __("Search Document Type"),
      fieldtype: "Data",
      change: () => this.render(),
    });

    this.page.set_primary_action(__("Save Changes"), () => this.save_changes(), "check");
    this.page.add_inner_button(__("Discard Changes"), () => this.discard_changes());
    this.page.add_inner_button(__("Collapse All"), () => this.collapse_all(), __("View"));
    this.page.add_inner_button(__("Expand All"), () => this.expand_all(), __("View"));
    this.page.add_inner_button(
      __("Dashboard"),
      () => frappe.set_route("permission-manager-dashboard"),
      __("Permission Manager")
    );
    this.page.add_inner_button(
      __("User Modules"),
      () => frappe.set_route("marina-user-module-manager"),
      __("Permission Manager")
    );
    this.page.add_inner_button(
      __("Pages and Reports"),
      () => frappe.set_route("marina-page-report-permission-manager"),
      __("Permission Manager")
    );
    this.page.add_inner_button(
      __("Workspaces"),
      () => frappe.set_route("marina-workspace-access-manager"),
      __("Permission Manager")
    );
    this.page.add_inner_button(
      __("User Permissions"),
      () => frappe.set_route("marina-user-permission-manager"),
      __("Permission Manager")
    );
    this.update_save_button();
  }

  make_body() {
    this.body = $("<div class='mpm-root'></div>").appendTo(this.page.main);
  }

  bind_events() {
    this.body.on("click", ".mpm-module-header", (event) => {
      if ($(event.target).is("input")) return;
      const group_index = Number($(event.currentTarget).attr("data-group-index"));
      this.toggle_group(group_index);
    });

    this.body.on("change", ".mpm-right", (event) => this.handle_right_change(event));
    this.body.on("change", ".mpm-bulk-right", (event) => this.handle_bulk_change(event));
    this.body.on("click", ".mpm-doctype-link", (event) => this.handle_doctype_link(event));
  }

  async handle_role_change() {
    const next_role = this.role_field.get_value();
    if (next_role === this.current_role) return;

    if (this.pending.size && this.current_role) {
      frappe.confirm(
        __("Discard the unsaved permission changes?"),
        () => this.load_role(next_role),
        () => this.role_field.set_value(this.current_role)
      );
      return;
    }

    await this.load_role(next_role);
  }

  async load_role(role) {
    if (!role) {
      this.current_role = null;
      this.rows = [];
      this.show_empty(__("Select a Role to load its complete permission matrix."));
      return;
    }

    const response = await frappe.call({
      method: "marina_custom_apps.permission_manager.api.permissions.get_permission_matrix",
      args: { role },
      freeze: true,
      freeze_message: __("Loading permissions..."),
    });

    this.current_role = role;
    this.rows = response.message.rows || [];
    this.initial_rights.clear();
    this.pending.clear();

    this.rows.forEach((row) => {
      row.key = this.row_key(row);
      this.initial_rights.set(row.key, JSON.stringify(row.rights));
    });

    this.populate_filter_options();
    this.update_save_button();
    this.render();
  }

  populate_filter_options() {
    const applications = [...new Set(this.rows.map((row) => row.app))].sort((a, b) =>
      a.localeCompare(b)
    );
    this.set_select_options(this.application_field, ["", ...applications]);
    this.application_field.set_value("");
    this.refresh_module_options();
  }

  handle_application_change() {
    this.refresh_module_options();
    this.render();
  }

  refresh_module_options() {
    const application = this.application_field.get_value();
    const modules = [
      ...new Set(
        this.rows
          .filter((row) => !application || row.app === application)
          .map((row) => row.module)
      ),
    ].sort((a, b) => a.localeCompare(b));
    this.set_select_options(this.module_field, ["", ...modules]);
    if (!modules.includes(this.module_field.get_value())) {
      this.module_field.set_value("");
    }
  }

  set_select_options(control, options) {
    control.df.options = options;
    control.refresh();
  }

  filtered_rows() {
    const application = this.application_field.get_value();
    const module = this.module_field.get_value();
    const status = this.status_field.get_value();
    const search = (this.search_field.get_value() || "").trim().toLowerCase();

    return this.rows.filter((row) => {
      if (application && row.app !== application) return false;
      if (module && row.module !== module) return false;
      if (search && !`${row.doctype} ${row.doctype_label}`.toLowerCase().includes(search)) return false;
      if (status === "Configured" && !row.configured) return false;
      if (status === "Unconfigured" && row.configured) return false;
      if (status === "Modified" && !this.pending.has(row.key)) return false;
      return true;
    });
  }

  render() {
    if (!this.current_role) return;

    const rows = this.filtered_rows();
    if (!rows.length) {
      this.show_empty(__("No Document Types match the selected filters."));
      return;
    }

    const grouped = new Map();
    rows.forEach((row) => {
      const key = `${row.app}|||${row.module}`;
      if (!grouped.has(key)) {
        grouped.set(key, {
          app: row.app,
          module: row.module,
          module_label: row.module_label,
          rows: [],
          open: Boolean(this.module_field.get_value() || this.search_field.get_value()),
        });
      }
      grouped.get(key).rows.push(row);
    });
    this.groups = [...grouped.values()];

    let current_app = null;
    const html = [];
    this.groups.forEach((group, index) => {
      if (group.app !== current_app) {
        current_app = group.app;
        html.push(`<h4 class="mpm-app-title">${this.escape(current_app)}</h4>`);
      }
      html.push(this.module_shell(group, index));
    });

    this.body.html(html.join(""));
    this.groups.forEach((group, index) => {
      if (group.open) this.render_group_table(index);
    });
  }

  module_shell(group, index) {
    const configured = new Set(group.rows.filter((row) => row.configured).map((row) => row.doctype)).size;
    const total = new Set(group.rows.map((row) => row.doctype)).size;
    const modified = group.rows.filter((row) => this.pending.has(row.key)).length;
    return `
      <section class="mpm-module" data-group-index="${index}">
        <button class="mpm-module-header" type="button" data-group-index="${index}">
          <span class="mpm-caret">${group.open ? "▾" : "▸"}</span>
          <span class="mpm-module-name">${this.escape(group.module_label)}</span>
          <span class="mpm-module-summary">${configured} ${__("configured")} / ${total}</span>
          ${modified ? `<span class="indicator-pill orange">${modified} ${__("modified")}</span>` : ""}
        </button>
        <div class="mpm-module-body" ${group.open ? "" : "hidden"}></div>
      </section>`;
  }

  toggle_group(group_index) {
    const group = this.groups[group_index];
    if (!group) return;
    group.open = !group.open;
    const section = this.body.find(`.mpm-module[data-group-index='${group_index}']`);
    section.find(".mpm-caret").text(group.open ? "▾" : "▸");
    section.find(".mpm-module-body").prop("hidden", !group.open);
    if (group.open && !section.find("table").length) this.render_group_table(group_index);
  }

  expand_all() {
    this.groups.forEach((group, index) => {
      if (!group.open) this.toggle_group(index);
    });
  }

  collapse_all() {
    this.groups.forEach((group, index) => {
      if (group.open) this.toggle_group(index);
    });
  }

  render_group_table(group_index) {
    const group = this.groups[group_index];
    const container = this.body.find(
      `.mpm-module[data-group-index='${group_index}'] .mpm-module-body`
    );
    const headers = this.rights.map((right) => `<th>${__(this.title(right))}</th>`).join("");
    const bulk = this.rights
      .map(
        (right) => `
          <th class="mpm-bulk-cell">
            <input type="checkbox" class="mpm-bulk-right" data-group-index="${group_index}"
              data-right="${right}" title="${this.escape(__("Apply to eligible Level 0 rows currently shown"))}">
          </th>`
      )
      .join("");
    const rows = group.rows.map((row) => this.row_html(row)).join("");

    container.html(`
      <div class="mpm-table-wrap">
        <table class="table table-bordered mpm-table">
          <thead>
            <tr class="mpm-bulk-row">
              <th colspan="4">${__("Apply to all eligible Level 0 documents currently shown")}</th>
              ${bulk}
            </tr>
            <tr>
              <th class="mpm-doctype-column">${__("Document Type")}</th>
              <th>${__("Level")}</th>
              <th>${__("If Owner")}</th>
              <th>${__("Source")}</th>
              ${headers}
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`);
    this.sync_bulk_states(group_index);
  }

  row_html(row) {
    const cells = this.rights
      .map((right) => {
        if (!this.is_applicable(row, right)) return '<td class="mpm-na">—</td>';
        return `
          <td class="mpm-check-cell">
            <input type="checkbox" class="mpm-right" data-row-key="${this.escape(row.key)}"
              data-right="${right}" ${row.rights[right] ? "checked" : ""}>
          </td>`;
      })
      .join("");
    const source = row.source === "custom" ? __("Custom") : row.source === "standard" ? __("Standard") : __("None");
    const source_class = row.source === "custom" ? "orange" : row.source === "standard" ? "blue" : "gray";
    const modified_class = this.pending.has(row.key) ? " mpm-row-modified" : "";
    const doctype_route = `/app/${frappe.router.slug(row.doctype)}`;

    return `
      <tr class="mpm-permission-row${modified_class}" data-row-key="${this.escape(row.key)}">
        <td class="mpm-doctype-column" title="${this.escape(row.doctype)}">
          <a class="mpm-doctype-link" href="${this.escape(doctype_route)}"
            data-doctype="${this.escape(row.doctype)}">${this.escape(row.doctype_label)}</a>
        </td>
        <td class="text-center">${row.permlevel}</td>
        <td class="text-center">${row.if_owner ? "✓" : "—"}</td>
        <td><span class="indicator-pill ${source_class}">${this.escape(source)}</span></td>
        ${cells}
      </tr>`;
  }

  handle_doctype_link(event) {
    // Preserve normal browser behavior for opening the DocType in another tab or window.
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) {
      return;
    }

    event.preventDefault();
    const doctype = $(event.currentTarget).attr("data-doctype");
    const open_doctype = () => frappe.set_route("List", doctype);

    if (this.pending.size) {
      frappe.confirm(
        __("You have unsaved permission changes. Open {0} without saving them?", [
          `<strong>${this.escape(doctype)}</strong>`,
        ]),
        open_doctype
      );
      return;
    }

    open_doctype();
  }

  handle_right_change(event) {
    const checkbox = $(event.currentTarget);
    const row = this.row_by_key(checkbox.attr("data-row-key"));
    const right = checkbox.attr("data-right");
    if (!row) return;

    row.rights[right] = checkbox.prop("checked") ? 1 : 0;
    this.apply_dependencies(row, right, Boolean(row.rights[right]));
    this.update_pending(row);
    this.sync_row(row);
    this.sync_group_for_row(row);
    this.update_save_button();
  }

  handle_bulk_change(event) {
    const checkbox = $(event.currentTarget);
    const group_index = Number(checkbox.attr("data-group-index"));
    const right = checkbox.attr("data-right");
    const checked = checkbox.prop("checked");
    const group = this.groups[group_index];

    group.rows
      .filter((row) => row.permlevel === 0 && !row.if_owner && this.is_applicable(row, right))
      .forEach((row) => {
        row.rights[right] = checked ? 1 : 0;
        this.apply_dependencies(row, right, checked);
        this.update_pending(row);
      });

    this.render_group_table(group_index);
    this.update_module_header(group_index);
    this.update_save_button();
  }

  apply_dependencies(row, right, checked) {
    if (checked) {
      if (["write", "create", "delete", "submit", "cancel", "amend", "report", "export", "print", "email", "share"].includes(right)) {
        row.rights.read = 1;
      }
      if (["submit", "cancel", "amend"].includes(right)) row.rights.write = 1;
      if (["cancel", "amend"].includes(right)) row.rights.submit = 1;
      if (right === "amend") row.rights.cancel = 1;
      if (right === "import") {
        row.rights.create = 1;
        row.rights.read = 1;
      }
    } else {
      if (right === "read") {
        ["write", "create", "delete", "submit", "cancel", "amend", "report", "import", "export", "print", "email", "share"].forEach(
          (dependent) => (row.rights[dependent] = 0)
        );
      }
      if (right === "write") ["submit", "cancel", "amend"].forEach((dependent) => (row.rights[dependent] = 0));
      if (right === "submit") ["cancel", "amend"].forEach((dependent) => (row.rights[dependent] = 0));
      if (right === "cancel") row.rights.amend = 0;
      if (right === "create") row.rights.import = 0;
    }
  }

  is_applicable(row, right) {
    if (row.permlevel > 0 && !["read", "write"].includes(right)) return false;
    if (!row.is_submittable && ["submit", "cancel", "amend"].includes(right)) return false;
    if (row.issingle && ["report", "import", "export"].includes(right)) return false;
    if (!row.allow_import && right === "import") return false;
    if (row.if_owner && right === "report") return false;
    return true;
  }

  update_pending(row) {
    const initial = this.initial_rights.get(row.key);
    const current = JSON.stringify(row.rights);
    if (initial === current) this.pending.delete(row.key);
    else this.pending.add(row.key);
  }

  sync_row(row) {
    const element = this.body.find(`tr[data-row-key='${this.escape_selector(row.key)}']`);
    element.toggleClass("mpm-row-modified", this.pending.has(row.key));
    this.rights.forEach((right) => {
      element.find(`input[data-right='${right}']`).prop("checked", Boolean(row.rights[right]));
    });
  }

  sync_group_for_row(row) {
    const group_index = this.groups.findIndex(
      (group) => group.app === row.app && group.module === row.module
    );
    if (group_index >= 0) {
      this.sync_bulk_states(group_index);
      this.update_module_header(group_index);
    }
  }

  sync_bulk_states(group_index) {
    const group = this.groups[group_index];
    const section = this.body.find(`.mpm-module[data-group-index='${group_index}']`);
    this.rights.forEach((right) => {
      const eligible = group.rows.filter(
        (row) => row.permlevel === 0 && !row.if_owner && this.is_applicable(row, right)
      );
      const selected = eligible.filter((row) => row.rights[right]).length;
      section
        .find(`.mpm-bulk-right[data-right='${right}']`)
        .prop("checked", Boolean(eligible.length && selected === eligible.length))
        .prop("indeterminate", selected > 0 && selected < eligible.length)
        .prop("disabled", !eligible.length);
    });
  }

  update_module_header(group_index) {
    const group = this.groups[group_index];
    const modified = group.rows.filter((row) => this.pending.has(row.key)).length;
    const header = this.body.find(
      `.mpm-module[data-group-index='${group_index}'] .mpm-module-header`
    );
    header.find(".indicator-pill").remove();
    if (modified) {
      header.append(`<span class="indicator-pill orange">${modified} ${__("modified")}</span>`);
    }
  }

  save_changes() {
    if (!this.pending.size) {
      frappe.show_alert({ message: __("There are no changes to save."), indicator: "blue" });
      return;
    }

    const changes = [...this.pending]
      .map((key) => this.row_by_key(key))
      .filter(Boolean)
      .map((row) => ({
        doctype: row.doctype,
        permlevel: row.permlevel,
        if_owner: row.if_owner,
        rights: row.rights,
      }));
    const doctypes = new Set(changes.map((change) => change.doctype)).size;

    frappe.confirm(
      __("Apply {0} changed permission rows across {1} Document Types for role {2}?", [
        changes.length,
        doctypes,
        `<strong>${this.escape(this.current_role)}</strong>`,
      ]),
      async () => {
        const response = await frappe.call({
          method: "marina_custom_apps.permission_manager.api.permissions.save_permission_matrix",
          args: { role: this.current_role, changes },
          freeze: true,
          freeze_message: __("Saving and validating permissions..."),
        });
        frappe.show_alert({
          message: __("Updated {0} permission rows.", [response.message.updated_rows]),
          indicator: "green",
        });
        await this.load_role(this.current_role);
      }
    );
  }

  discard_changes() {
    if (!this.pending.size) return;
    frappe.confirm(__("Discard all unsaved permission changes?"), () => {
      this.rows.forEach((row) => {
        row.rights = JSON.parse(this.initial_rights.get(row.key));
      });
      this.pending.clear();
      this.update_save_button();
      this.render();
    });
  }

  update_save_button() {
    const count = this.pending.size;
    const label = count ? __("Save Changes ({0})", [count]) : __("Save Changes");
    this.page.set_primary_action(label, () => this.save_changes(), "check");
    this.page.btn_primary.prop("disabled", !count);
  }

  show_empty(message) {
    this.body.html(`<div class="mpm-empty text-muted">${this.escape(message)}</div>`);
  }

  row_key(row) {
    return `${row.doctype}|||${row.permlevel}|||${row.if_owner}`;
  }

  row_by_key(key) {
    return this.rows.find((row) => row.key === key);
  }

  title(value) {
    return value
      .split("_")
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
  }

  escape(value) {
    return $("<div>").text(value == null ? "" : String(value)).html();
  }

  escape_selector(value) {
    return String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'");
  }
}
