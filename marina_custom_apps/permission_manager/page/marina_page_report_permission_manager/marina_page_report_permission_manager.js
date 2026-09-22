frappe.pages["marina-page-report-permission-manager"].on_page_load = (wrapper) => {
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: __("Page and Report Permissions"),
    single_column: true,
  });

  frappe.breadcrumbs.add("Setup");
  wrapper.page_report_permission_manager = new MarinaPageReportPermissionManager(page);
};

class MarinaPageReportPermissionManager {
  constructor(page) {
    this.page = page;
    this.rows = [];
    this.initial_access = new Map();
    this.pending = new Set();
    this.selected_open = new Set();
    this.current_role = null;
    this.current_resource_type = "Page";
    this.groups = [];

    this.make_controls();
    this.make_body();
    this.bind_events();
    this.show_empty(__("Select a Role to load Page permissions."));
    this.update_save_button();
  }

  make_controls() {
    this.resource_type_field = this.page.add_field({
      fieldname: "resource_type",
      label: __("Permission Type"),
      fieldtype: "Select",
      options: ["Page", "Report"],
      default: "Page",
      reqd: 1,
      change: () => this.handle_selection_change(),
    });

    this.role_field = this.page.add_field({
      fieldname: "role",
      label: __("Role"),
      fieldtype: "Link",
      options: "Role",
      reqd: 1,
      get_query: () => ({
        filters: { disabled: 0, name: ["not in", ["All", "Guest", "Desk User"]] },
      }),
      change: () => this.handle_selection_change(),
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
      options: ["", "Allowed", "Restricted", "Customized", "Open to All", "Modified"],
      change: () => this.render(),
    });

    this.search_field = this.page.add_field({
      fieldname: "search",
      label: __("Search"),
      fieldtype: "Data",
      change: () => this.render(),
    });

    this.page.set_primary_action(__("Save Changes"), () => this.save_changes(), "check");
    this.page.add_inner_button(__("Discard Changes"), () => this.discard_changes());
    this.page.add_inner_button(
      __("Dashboard"),
      () => frappe.set_route("permission-manager-dashboard"),
      __("Permission Manager")
    );
    this.page.add_inner_button(
      __("Role Permissions"),
      () => frappe.set_route("marina-permission-manager"),
      __("Permission Manager")
    );
    this.page.add_inner_button(
      __("User Modules"),
      () => frappe.set_route("marina-user-module-manager"),
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
  }

  make_body() {
    this.body = $("<div class='mpm-root prpm-root'></div>").appendTo(this.page.main);
  }

  bind_events() {
    this.body.on("click", ".prpm-module-header", (event) => {
      if ($(event.target).is("input")) return;
      this.toggle_group(Number($(event.currentTarget).attr("data-group-index")));
    });
    this.body.on("change", ".prpm-allowed", (event) => this.handle_access_change(event));
    this.body.on("change", ".prpm-bulk-allowed", (event) => this.handle_bulk_change(event));
    this.body.on("change", ".prpm-select-open", (event) => this.handle_open_selection(event));
    this.body.on("change", ".prpm-bulk-select-open", (event) =>
      this.handle_bulk_open_selection(event)
    );
    this.body.on("click", ".prpm-select-visible-open", () => this.select_visible_open());
    this.body.on("click", ".prpm-clear-open-selection", () => this.clear_open_selection());
    this.body.on("click", ".prpm-restrict-open", () => this.open_restriction_dialog());
    this.body.on("click", ".prpm-resource-link", (event) => this.handle_resource_link(event));
  }

  handle_selection_change() {
    const next_role = this.role_field.get_value();
    const next_type = this.resource_type_field.get_value() || "Page";
    if (next_role === this.current_role && next_type === this.current_resource_type) return;

    if ((this.pending.size || this.selected_open.size) && this.current_role) {
      frappe.confirm(
        __("Discard the unsaved permission changes and bulk selection?"),
        () => this.load_matrix(next_role, next_type),
        () => {
          this.role_field.set_value(this.current_role);
          this.resource_type_field.set_value(this.current_resource_type);
        }
      );
      return;
    }
    this.load_matrix(next_role, next_type);
  }

  async load_matrix(role, resource_type) {
    if (!role) {
      this.current_role = null;
      this.current_resource_type = resource_type;
      this.rows = [];
      this.pending.clear();
      this.selected_open.clear();
      this.update_save_button();
      this.show_empty(__("Select a Role to load {0} permissions.", [resource_type]));
      return;
    }

    const response = await frappe.call({
      method: "marina_custom_apps.permission_manager.api.page_reports.get_page_report_matrix",
      args: { role, resource_type },
      freeze: true,
      freeze_message: __("Loading Page and Report permissions..."),
    });
    this.current_role = role;
    this.current_resource_type = resource_type;
    this.rows = response.message.rows || [];
    this.initial_access.clear();
    this.pending.clear();
    this.selected_open.clear();
    this.rows.forEach((row) => {
      row.allowed = Boolean(row.allowed);
      this.initial_access.set(row.resource, row.allowed);
    });
    this.populate_filter_options();
    this.update_save_button();
    this.render();
  }

  populate_filter_options() {
    const applications = [...new Set(this.rows.map((row) => row.app))];
    this.application_field.df.options = ["", ...applications];
    this.application_field.set_value("");
    this.application_field.refresh();
    this.populate_module_options();
  }

  handle_application_change() {
    this.populate_module_options();
    this.render();
  }

  populate_module_options() {
    const application = this.application_field.get_value();
    const modules = [
      ...new Set(
        this.rows.filter((row) => !application || row.app === application).map((row) => row.module)
      ),
    ];
    this.module_field.df.options = ["", ...modules];
    if (!modules.includes(this.module_field.get_value())) this.module_field.set_value("");
    this.module_field.refresh();
  }

  visible_rows() {
    const application = this.application_field.get_value();
    const module = this.module_field.get_value();
    const status = this.status_field.get_value();
    const search = (this.search_field.get_value() || "").trim().toLowerCase();
    return this.rows.filter((row) => {
      if (application && row.app !== application) return false;
      if (module && row.module !== module) return false;
      if (status === "Allowed" && !row.allowed) return false;
      if (status === "Restricted" && row.allowed) return false;
      if (status === "Customized" && row.source !== "custom") return false;
      if (status === "Open to All" && !row.open_to_all) return false;
      if (status === "Modified" && !this.pending.has(row.resource)) return false;
      if (
        search &&
        !`${row.label} ${row.resource} ${row.ref_doctype || ""}`.toLowerCase().includes(search)
      ) {
        return false;
      }
      return true;
    });
  }

  build_groups(rows) {
    const previous = new Map(this.groups.map((group) => [group.key, group.open]));
    const groups = new Map();
    rows.forEach((row) => {
      const key = `${row.app}::${row.module}`;
      if (!groups.has(key)) {
        groups.set(key, { key, app: row.app, module: row.module, rows: [], open: previous.get(key) ?? true });
      }
      groups.get(key).rows.push(row);
    });
    this.groups = [...groups.values()];
  }

  render() {
    if (!this.current_role) {
      this.show_empty(__("Select a Role to load Page or Report permissions."));
      return;
    }
    const rows = this.visible_rows();
    this.build_groups(rows);
    if (!rows.length) {
      this.show_empty(__("No Pages or Reports match the current filters."));
      return;
    }

    const html = [this.render_bulk_toolbar(rows)];
    let current_app = null;
    this.groups.forEach((group, index) => {
      if (group.app !== current_app) {
        current_app = group.app;
        html.push(`<h4 class="prpm-app-title">${this.escape(current_app)}</h4>`);
      }
      const allowed = group.rows.filter((row) => row.allowed).length;
      html.push(`
        <section class="prpm-module" data-group-index="${index}">
          <button class="prpm-module-header" type="button" data-group-index="${index}">
            <span class="prpm-caret">${group.open ? "▾" : "▸"}</span>
            <span class="prpm-module-name">${this.escape(group.module)}</span>
            <span class="prpm-module-summary">${allowed} ${__("allowed")} / ${group.rows.length}</span>
          </button>
          <div class="prpm-module-body" ${group.open ? "" : "hidden"}>
            ${this.render_group_table(group, index)}
          </div>
        </section>
      `);
    });
    this.body.html(html.join(""));
    this.groups.forEach((group, index) => this.update_bulk_checkbox(group, index));
    this.groups.forEach((group, index) => this.update_bulk_open_checkbox(group, index));
  }

  render_bulk_toolbar(rows) {
    const visible_open = rows.filter((row) => row.open_to_all).length;
    const selected = this.selected_open.size;
    return `
      <div class="prpm-restriction-toolbar">
        <div>
          <strong>${__("Open-to-All Restriction")}</strong>
          <div class="text-muted small prpm-selection-summary">
            ${__("{0} selected; {1} open resources currently visible", [selected, visible_open])}
          </div>
        </div>
        <div class="prpm-restriction-actions">
          <button type="button" class="btn btn-xs btn-default prpm-select-visible-open"
            ${visible_open ? "" : "disabled"}>${__("Select Visible Open to All")}</button>
          <button type="button" class="btn btn-xs btn-default prpm-clear-open-selection"
            ${selected ? "" : "disabled"}>${__("Clear Selection")}</button>
          <button type="button" class="btn btn-xs btn-primary prpm-restrict-open"
            ${selected ? "" : "disabled"}>${__("Restrict Selected ({0})", [selected])}</button>
        </div>
      </div>
    `;
  }

  render_group_table(group, group_index) {
    const rows = group.rows.map((row) => this.render_row(row)).join("");
    return `
      <div class="prpm-table-wrap">
        <table class="table table-bordered prpm-table">
          <thead><tr>
            <th class="prpm-select-cell">
              <input type="checkbox" class="prpm-bulk-select-open" data-group-index="${group_index}"
                title="${this.escape(__("Select open resources in this module"))}">
            </th>
            <th class="prpm-name-column">${this.escape(this.current_resource_type)}</th>
            <th>${__("Technical Name")}</th>
            <th>${__("Reference / Type")}</th>
            <th>${__("Source")}</th>
            <th class="prpm-check-cell">
              <label class="prpm-bulk-label">
                <input type="checkbox" class="prpm-bulk-allowed" data-group-index="${group_index}">
                <span>${__("Allowed")}</span>
              </label>
            </th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  }

  render_row(row) {
    const modified = this.pending.has(row.resource) ? " prpm-row-modified" : "";
    const detail = row.resource_type === "Report" ? row.ref_doctype || row.report_type || "" : "";
    const source = row.source === "custom" ? __("Customized") : row.source === "open" ? __("Open to All") : __("Standard");
    const source_color = row.source === "custom" ? "orange" : row.source === "open" ? "blue" : "gray";
    const disabled = row.open_to_all ? "disabled" : "";
    const title = row.open_to_all
      ? __("Open to all roles. Select this row and use Restrict Selected to assign an explicit role list.")
      : "";
    const href = this.resource_href(row);
    return `
      <tr class="prpm-row${modified}" data-resource="${this.escape(row.resource)}">
        <td class="prpm-select-cell">
          <input type="checkbox" class="prpm-select-open" data-resource="${this.escape(row.resource)}"
            ${this.selected_open.has(row.resource) ? "checked" : ""}
            ${row.open_to_all ? "" : "disabled"}
            title="${this.escape(row.open_to_all ? __("Select for explicit role restriction") : __("Only Open-to-All resources can be converted"))}">
        </td>
        <td class="prpm-name-column">
          <a class="prpm-resource-link" href="${this.escape(href)}"
            data-resource="${this.escape(row.resource)}" title="${__("Open {0}", [this.escape(row.label)])}">
            ${this.escape(row.label)} <span aria-hidden="true">↗</span>
          </a>
        </td>
        <td>${this.escape(row.resource)}</td>
        <td>${this.escape(detail)}</td>
        <td><span class="indicator-pill ${source_color}">${this.escape(source)}</span></td>
        <td class="prpm-check-cell" title="${this.escape(title)}">
          <input type="checkbox" class="prpm-allowed" data-resource="${this.escape(row.resource)}"
            ${row.allowed ? "checked" : ""} ${disabled}>
        </td>
      </tr>
    `;
  }

  resource_route(row) {
    if (row.resource_type === "Page") return [row.resource];
    if (row.report_type === "Report Builder" && row.ref_doctype) {
      return ["List", row.ref_doctype, "Report", row.resource];
    }
    return ["query-report", row.resource];
  }

  resource_href(row) {
    const route = frappe.router.convert_from_standard_route([...this.resource_route(row)]);
    return frappe.router.make_url(route);
  }

  handle_resource_link(event) {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.button === 1) return;
    event.preventDefault();
    const resource = $(event.currentTarget).attr("data-resource");
    const row = this.row_by_resource(resource);
    if (!row) return;
    const open = () => frappe.set_route(this.resource_route(row));
    if (this.pending.size || this.selected_open.size) {
      frappe.confirm(
        __("Open this {0} and leave the current unsaved changes or bulk selection?", [row.resource_type]),
        open
      );
      return;
    }
    open();
  }

  toggle_group(index) {
    const group = this.groups[index];
    if (!group) return;
    group.open = !group.open;
    const section = this.body.find(`.prpm-module[data-group-index='${index}']`);
    section.find(".prpm-caret").text(group.open ? "▾" : "▸");
    section.find(".prpm-module-body").prop("hidden", !group.open);
  }

  handle_open_selection(event) {
    const input = $(event.currentTarget);
    const resource = input.attr("data-resource");
    const row = this.row_by_resource(resource);
    if (!row || !row.open_to_all) return;
    if (input.is(":checked")) {
      this.selected_open.add(resource);
    } else {
      this.selected_open.delete(resource);
    }
    const group_index = Number(input.closest(".prpm-module").attr("data-group-index"));
    this.update_bulk_open_checkbox(this.groups[group_index], group_index);
    this.update_restriction_toolbar();
  }

  handle_bulk_open_selection(event) {
    const input = $(event.currentTarget);
    const group_index = Number(input.attr("data-group-index"));
    const group = this.groups[group_index];
    if (!group) return;
    group.rows.filter((row) => row.open_to_all).forEach((row) => {
      if (input.is(":checked")) {
        this.selected_open.add(row.resource);
      } else {
        this.selected_open.delete(row.resource);
      }
    });
    input.closest(".prpm-module").find(".prpm-select-open").each((_, element) => {
      const row_input = $(element);
      row_input.prop("checked", this.selected_open.has(row_input.attr("data-resource")));
    });
    this.update_bulk_open_checkbox(group, group_index);
    this.update_restriction_toolbar();
  }

  select_visible_open() {
    this.visible_rows()
      .filter((row) => row.open_to_all)
      .forEach((row) => this.selected_open.add(row.resource));
    this.render();
  }

  clear_open_selection() {
    this.selected_open.clear();
    this.render();
  }

  update_restriction_toolbar() {
    const selected = this.selected_open.size;
    const visible_open = this.visible_rows().filter((row) => row.open_to_all).length;
    this.body
      .find(".prpm-selection-summary")
      .text(__("{0} selected; {1} open resources currently visible", [selected, visible_open]));
    this.body.find(".prpm-clear-open-selection").prop("disabled", !selected);
    this.body
      .find(".prpm-restrict-open")
      .prop("disabled", !selected)
      .text(__("Restrict Selected ({0})", [selected]));
  }

  update_bulk_open_checkbox(group, group_index) {
    if (!group) return;
    const eligible = group.rows.filter((row) => row.open_to_all);
    const selected = eligible.filter((row) => this.selected_open.has(row.resource)).length;
    this.body
      .find(`.prpm-module[data-group-index='${group_index}'] .prpm-bulk-select-open`)
      .prop("checked", Boolean(eligible.length && selected === eligible.length))
      .prop("indeterminate", selected > 0 && selected < eligible.length)
      .prop("disabled", !eligible.length);
  }

  open_restriction_dialog() {
    if (!this.selected_open.size) return;
    if (this.pending.size) {
      frappe.msgprint(__("Save or discard the current Allowed changes before restricting open resources."));
      return;
    }

    const selected_count = this.selected_open.size;
    const dialog = new frappe.ui.Dialog({
      title: __("Restrict {0} Open-to-All {1}", [selected_count, this.current_resource_type]),
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "explanation",
          options: `<p>${__(
            "Open access will be replaced by the exact role list below. Roles not selected will lose access to these resources."
          )}</p>`,
        },
        {
          fieldtype: "Table",
          fieldname: "roles",
          label: __("Roles That Retain Access"),
          cannot_add_rows: false,
          cannot_delete_rows: false,
          in_place_edit: true,
          data: this.current_role ? [{ role: this.current_role }] : [],
          fields: [
            {
              fieldtype: "Link",
              fieldname: "role",
              label: __("Role"),
              options: "Role",
              reqd: 1,
              in_list_view: 1,
              get_query: () => ({
                filters: { disabled: 0, name: ["not in", ["All", "Guest", "Desk User"]] },
              }),
            },
          ],
        },
      ],
      primary_action_label: __("Restrict Selected"),
      primary_action: async (values) => {
        const roles = [...new Set((values.roles || []).map((row) => row.role).filter(Boolean))];
        if (!roles.length) {
          frappe.msgprint(__("Select at least one Role that should retain access."));
          return;
        }
        dialog.hide();
        const response = await frappe.call({
          method: "marina_custom_apps.permission_manager.api.page_reports.restrict_open_resources",
          args: {
            resource_type: this.current_resource_type,
            resources: [...this.selected_open],
            roles,
          },
          freeze: true,
          freeze_message: __("Replacing open access with explicit roles..."),
        });
        const result = response.message || {};
        frappe.show_alert({
          message: __("Restricted {0} resources; skipped {1} resources changed by another user.", [
            result.updated_rows || 0,
            result.skipped_rows || 0,
          ]),
          indicator: "green",
        });
        this.selected_open.clear();
        await this.load_matrix(this.current_role, this.current_resource_type);
      },
    });
    dialog.show();
  }

  handle_access_change(event) {
    const input = $(event.currentTarget);
    const row = this.row_by_resource(input.attr("data-resource"));
    if (!row || row.open_to_all) return;
    row.allowed = input.is(":checked");
    this.update_pending(row);
    input.closest("tr").toggleClass("prpm-row-modified", this.pending.has(row.resource));
    this.update_save_button();
    const group_index = Number(input.closest(".prpm-module").attr("data-group-index"));
    this.update_bulk_checkbox(this.groups[group_index], group_index);
  }

  handle_bulk_change(event) {
    const input = $(event.currentTarget);
    const group_index = Number(input.attr("data-group-index"));
    const group = this.groups[group_index];
    const allowed = input.is(":checked");
    if (!group) return;
    group.rows.filter((row) => !row.open_to_all).forEach((row) => {
      row.allowed = allowed;
      this.update_pending(row);
    });
    this.update_save_button();
    this.render();
  }

  update_pending(row) {
    if (row.allowed === this.initial_access.get(row.resource)) {
      this.pending.delete(row.resource);
    } else {
      this.pending.add(row.resource);
    }
  }

  update_bulk_checkbox(group, group_index) {
    if (!group) return;
    const eligible = group.rows.filter((row) => !row.open_to_all);
    const selected = eligible.filter((row) => row.allowed).length;
    this.body
      .find(`.prpm-module[data-group-index='${group_index}'] .prpm-bulk-allowed`)
      .prop("checked", Boolean(eligible.length && selected === eligible.length))
      .prop("indeterminate", selected > 0 && selected < eligible.length)
      .prop("disabled", !eligible.length);
  }

  save_changes() {
    if (!this.pending.size) {
      frappe.show_alert({ message: __("There are no changes to save."), indicator: "blue" });
      return;
    }
    const changes = [...this.pending]
      .map((resource) => this.row_by_resource(resource))
      .filter(Boolean)
      .map((row) => ({ resource: row.resource, allowed: row.allowed ? 1 : 0 }));
    frappe.confirm(
      __("Apply {0} {1} permission changes for role {2}?", [
        changes.length,
        this.current_resource_type,
        `<strong>${this.escape(this.current_role)}</strong>`,
      ]),
      async () => {
        const response = await frappe.call({
          method: "marina_custom_apps.permission_manager.api.page_reports.save_page_report_matrix",
          args: {
            role: this.current_role,
            resource_type: this.current_resource_type,
            changes,
          },
          freeze: true,
          freeze_message: __("Saving Page and Report permissions..."),
        });
        frappe.show_alert({
          message: __("Updated {0} permission rows.", [response.message.updated_rows]),
          indicator: "green",
        });
        await this.load_matrix(this.current_role, this.current_resource_type);
      }
    );
  }

  discard_changes() {
    if (!this.pending.size && !this.selected_open.size) return;
    frappe.confirm(__("Discard all unsaved permission changes and bulk selections?"), () => {
      this.rows.forEach((row) => {
        row.allowed = this.initial_access.get(row.resource);
      });
      this.pending.clear();
      this.selected_open.clear();
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

  row_by_resource(resource) {
    return this.rows.find((row) => row.resource === resource);
  }

  show_empty(message) {
    this.body.html(`<div class="prpm-empty text-muted">${this.escape(message)}</div>`);
  }

  escape(value) {
    return $("<div>").text(value == null ? "" : String(value)).html();
  }
}
