frappe.pages["marina-workspace-access-manager"].on_page_load = (wrapper) => {
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: __("Workspace Access Manager"),
    single_column: true,
  });

  frappe.breadcrumbs.add("Setup");
  wrapper.workspace_access_manager = new MarinaWorkspaceAccessManager(page);
};

class MarinaWorkspaceAccessManager {
  constructor(page) {
    this.page = page;
    this.current_workspace = null;
    this.workspace = null;
    this.roles = [];
    this.users = [];
    this.page_override_roles = new Set();
    this.initial_roles = new Map();

    this.make_controls();
    this.make_body();
    this.bind_events();
    this.show_empty(__("Select an active Workspace to manage its allowed roles."));
    this.update_save_button();
  }

  make_controls() {
    this.workspace_field = this.page.add_field({
      fieldname: "workspace",
      label: __("Workspace"),
      fieldtype: "Link",
      options: "Workspace",
      reqd: 1,
      get_query: () => ({ filters: { is_hidden: 0 } }),
      change: () => this.handle_workspace_change(),
    });

    this.view_field = this.page.add_field({
      fieldname: "view",
      label: __("View"),
      fieldtype: "Select",
      options: ["Roles", "Users"],
      default: "Roles",
      reqd: 1,
      change: () => this.handle_view_change(),
    });

    this.status_field = this.page.add_field({
      fieldname: "status",
      label: __("Status"),
      fieldtype: "Select",
      options: ["", "Assigned", "Unassigned", "Page Override", "Modified"],
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
      __("Open Workspace"),
      () => this.open_workspace(),
      __("View")
    );
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
      __("Pages and Reports"),
      () => frappe.set_route("marina-page-report-permission-manager"),
      __("Permission Manager")
    );
    this.page.add_inner_button(
      __("User Permissions"),
      () => frappe.set_route("marina-user-permission-manager"),
      __("Permission Manager")
    );
  }

  make_body() {
    this.body = $("<div class='mpm-root wam-root'></div>").appendTo(this.page.main);
  }

  bind_events() {
    this.body.on("change", ".wam-role-check", (event) => this.handle_role_change(event));
    this.body.on("change", ".wam-bulk-role", (event) => this.handle_bulk_change(event));
    this.body.on("click", ".wam-open-workspace", () => this.open_workspace());
  }

  has_pending() {
    return this.roles.some((role) => role.assigned !== this.initial_roles.get(role.role));
  }

  async handle_workspace_change() {
    const next_workspace = this.workspace_field.get_value();
    if (next_workspace === this.current_workspace) return;

    if (this.has_pending() && this.current_workspace) {
      frappe.confirm(
        __("Discard the unsaved Workspace role changes?"),
        () => this.load_workspace(next_workspace),
        () => this.workspace_field.set_value(this.current_workspace)
      );
      return;
    }
    await this.load_workspace(next_workspace);
  }

  async load_workspace(workspace) {
    if (!workspace) {
      this.current_workspace = null;
      this.workspace = null;
      this.roles = [];
      this.users = [];
      this.initial_roles.clear();
      this.update_save_button();
      this.show_empty(__("Select an active Workspace to manage its allowed roles."));
      return;
    }

    const response = await frappe.call({
      method: "marina_custom_apps.permission_manager.api.workspaces.get_workspace_access",
      args: { workspace },
      freeze: true,
      freeze_message: __("Loading Workspace access..."),
    });
    this.current_workspace = workspace;
    this.workspace = response.message.workspace;
    this.roles = response.message.roles || [];
    this.users = response.message.users || [];
    this.page_override_roles = new Set(response.message.page_override_roles || []);
    this.initial_roles.clear();
    this.roles.forEach((role) => {
      role.assigned = Boolean(role.assigned);
      role.page_override = Boolean(role.page_override);
      this.initial_roles.set(role.role, role.assigned);
    });
    this.recalculate_users();
    this.update_save_button();
    this.render();
  }

  handle_view_change() {
    const roles_view = this.view_field.get_value() !== "Users";
    this.status_field.df.options = roles_view
      ? ["", "Assigned", "Unassigned", "Page Override", "Modified"]
      : ["", "Allowed", "Restricted", "Workspace Manager"];
    this.status_field.set_value("");
    this.status_field.refresh();
    this.render();
  }

  visible_roles() {
    const status = this.status_field.get_value();
    const search = (this.search_field.get_value() || "").trim().toLowerCase();
    return this.roles.filter((role) => {
      if (status === "Assigned" && !role.assigned) return false;
      if (status === "Unassigned" && role.assigned) return false;
      if (status === "Page Override" && !role.page_override) return false;
      if (status === "Modified" && role.assigned === this.initial_roles.get(role.role)) return false;
      return !search || role.role.toLowerCase().includes(search);
    });
  }

  visible_users() {
    const status = this.status_field.get_value();
    const search = (this.search_field.get_value() || "").trim().toLowerCase();
    return this.users.filter((user) => {
      if (status === "Allowed" && !user.allowed) return false;
      if (status === "Restricted" && user.allowed) return false;
      if (status === "Workspace Manager" && !user.roles.includes("Workspace Manager")) return false;
      const haystack = `${user.full_name} ${user.user} ${user.roles.join(" ")}`.toLowerCase();
      return !search || haystack.includes(search);
    });
  }

  effective_roles() {
    return new Set([
      ...this.roles.filter((role) => role.assigned).map((role) => role.role),
      ...this.page_override_roles,
    ]);
  }

  is_open_to_all(allowed_roles = this.effective_roles()) {
    return !allowed_roles.size || allowed_roles.has("All") || allowed_roles.has("Desk User");
  }

  recalculate_users() {
    if (!this.workspace) return;
    const allowed_roles = this.effective_roles();
    this.users.forEach((user) => {
      const user_roles = new Set(user.roles);
      if (!this.workspace.public) {
        user.allowed = Boolean(this.workspace.for_user && user.user === this.workspace.for_user);
        user.reason = user.allowed ? __("Private owner") : __("Private workspace");
        user.matching_roles = [];
      } else if (user_roles.has("Workspace Manager")) {
        user.allowed = true;
        user.reason = __("Workspace Manager");
        user.matching_roles = ["Workspace Manager"];
      } else if (this.is_open_to_all(allowed_roles)) {
        user.allowed = true;
        user.reason = __("Open to all Desk users");
        user.matching_roles = [];
      } else {
        user.matching_roles = [...allowed_roles].filter((role) => user_roles.has(role)).sort();
        user.allowed = Boolean(user.matching_roles.length);
        user.reason = user.allowed ? __("Matching role") : __("No matching role");
      }
    });
  }

  render() {
    if (!this.workspace) {
      this.show_empty(__("Select an active Workspace to manage its allowed roles."));
      return;
    }
    const view = this.view_field.get_value() || "Roles";
    const allowed_users = this.users.filter((user) => user.allowed).length;
    const native_roles = this.roles.filter((role) => role.assigned).length;
    const access_mode = this.workspace.public
      ? this.is_open_to_all()
        ? __("Open to all Desk users")
        : __("Role restricted")
      : __("Private user workspace");
    const warning = this.workspace.public
      ? this.is_open_to_all()
        ? `<div class="alert alert-warning wam-notice">${__("No roles are assigned, so Frappe treats this Workspace as open to all Desk users.")}</div>`
        : this.page_override_roles.size
          ? `<div class="alert alert-info wam-notice">${__("Some effective roles come from Page overrides. They are shown here but must be changed in Page and Report Permissions.")}</div>`
          : ""
      : `<div class="alert alert-warning wam-notice">${__("This is a private Workspace for {0}. Frappe does not use its Roles table for user assignment. Convert it to Public before managing roles.", [this.escape(this.workspace.for_user || __("an individual user"))])}</div>`;

    this.body.html(`
      <section class="wam-summary">
        <div>
          <button type="button" class="btn btn-link wam-open-workspace">${this.escape(this.workspace.title)}</button>
          <div class="text-muted">${this.escape(this.workspace.name)} · ${this.escape(this.workspace.module || __("Unassigned"))}</div>
        </div>
        <div class="wam-metrics">
          <span class="indicator-pill ${this.workspace.public ? "blue" : "orange"}">${this.escape(access_mode)}</span>
          <span>${native_roles} ${__("workspace roles")}</span>
          <span>${allowed_users} ${__("matching users")} / ${this.users.length}</span>
        </div>
      </section>
      ${warning}
      <div class="wam-help text-muted">${__("User results show the Workspace role gate. Module, domain, and document permissions can still further restrict access.")}</div>
      ${view === "Users" ? this.render_users() : this.render_roles()}
    `);
    if (view !== "Users") this.update_bulk_checkbox();
  }

  render_roles() {
    const roles = this.visible_roles();
    if (!roles.length) return `<div class="wam-empty text-muted">${__("No roles match the current filters.")}</div>`;
    const disabled = this.workspace.editable ? "" : "disabled";
    return `
      <div class="wam-table-wrap">
        <table class="table table-bordered wam-table">
          <colgroup><col style="width:38%"><col style="width:16%"><col style="width:26%"><col style="width:20%"></colgroup>
          <thead><tr>
            <th>${__("Role")}</th>
            <th>${__("Active Users")}</th>
            <th>${__("Additional Source")}</th>
            <th class="wam-check-cell">
              <label><input type="checkbox" class="wam-bulk-role" ${disabled}> ${__("Workspace Role")}</label>
            </th>
          </tr></thead>
          <tbody>${roles.map((role) => this.render_role(role, disabled)).join("")}</tbody>
        </table>
      </div>`;
  }

  render_role(role, disabled) {
    const modified = role.assigned !== this.initial_roles.get(role.role) ? " wam-row-modified" : "";
    const override = role.page_override
      ? `<span class="indicator-pill orange">${__("Page Override")}</span>`
      : `<span class="text-muted">—</span>`;
    return `
      <tr class="wam-role-row${modified}" data-role="${this.escape(role.role)}">
        <td>${this.escape(role.role)}</td>
        <td>${role.active_users}</td>
        <td>${override}</td>
        <td class="wam-check-cell"><input type="checkbox" class="wam-role-check"
          data-role="${this.escape(role.role)}" ${role.assigned ? "checked" : ""} ${disabled}></td>
      </tr>`;
  }

  render_users() {
    const users = this.visible_users();
    if (!users.length) return `<div class="wam-empty text-muted">${__("No active users match the current filters.")}</div>`;
    return `
      <div class="wam-table-wrap">
        <table class="table table-bordered wam-table wam-user-table">
          <colgroup><col style="width:22%"><col style="width:27%"><col style="width:18%"><col style="width:23%"><col style="width:10%"></colgroup>
          <thead><tr>
            <th>${__("User")}</th>
            <th>${__("Email")}</th>
            <th>${__("Access Reason")}</th>
            <th>${__("Matching Roles")}</th>
            <th class="wam-check-cell">${__("Role Gate Access")}</th>
          </tr></thead>
          <tbody>${users.map((user) => `
            <tr>
              <td>${this.escape(user.full_name)}</td>
              <td>${this.escape(user.user)}</td>
              <td>${this.escape(user.reason)}</td>
              <td>${this.escape(user.matching_roles.join(", ") || "—")}</td>
              <td class="wam-check-cell"><input type="checkbox" ${user.allowed ? "checked" : ""} disabled></td>
            </tr>`).join("")}</tbody>
        </table>
      </div>`;
  }

  handle_role_change(event) {
    const input = $(event.currentTarget);
    const role = this.roles.find((item) => item.role === input.attr("data-role"));
    if (!role || !this.workspace.editable) return;
    role.assigned = input.is(":checked");
    this.recalculate_users();
    this.update_save_button();
    this.render();
  }

  handle_bulk_change(event) {
    if (!this.workspace.editable) return;
    const assigned = $(event.currentTarget).is(":checked");
    this.visible_roles().forEach((role) => { role.assigned = assigned; });
    this.recalculate_users();
    this.update_save_button();
    this.render();
  }

  update_bulk_checkbox() {
    const roles = this.visible_roles();
    const selected = roles.filter((role) => role.assigned).length;
    this.body.find(".wam-bulk-role")
      .prop("checked", Boolean(roles.length && selected === roles.length))
      .prop("indeterminate", selected > 0 && selected < roles.length)
      .prop("disabled", !roles.length || !this.workspace.editable);
  }

  save_changes() {
    if (!this.has_pending() || !this.workspace?.editable) {
      frappe.show_alert({ message: __("There are no changes to save."), indicator: "blue" });
      return;
    }
    const roles = this.roles.filter((role) => role.assigned).map((role) => role.role);
    const resulting_roles = new Set([...roles, ...this.page_override_roles]);
    const open_warning = this.is_open_to_all(resulting_roles)
      ? ` ${__("This will make the Workspace open to all Desk users.")}`
      : "";
    frappe.confirm(
      __("Replace the allowed roles for Workspace {0} with {1} selected roles?", [
        `<strong>${this.escape(this.workspace.title)}</strong>`, roles.length,
      ]) + open_warning,
      async () => {
        const response = await frappe.call({
          method: "marina_custom_apps.permission_manager.api.workspaces.save_workspace_roles",
          args: { workspace: this.current_workspace, roles },
          freeze: true,
          freeze_message: __("Saving Workspace roles..."),
        });
        frappe.show_alert({
          message: __("Workspace access updated with {0} roles.", [response.message.assigned_roles]),
          indicator: "green",
        });
        await this.load_workspace(this.current_workspace);
      }
    );
  }

  discard_changes() {
    if (!this.has_pending()) return;
    frappe.confirm(__("Discard all unsaved Workspace role changes?"), () => {
      this.roles.forEach((role) => { role.assigned = this.initial_roles.get(role.role); });
      this.recalculate_users();
      this.update_save_button();
      this.render();
    });
  }

  update_save_button() {
    const count = this.roles.filter((role) => role.assigned !== this.initial_roles.get(role.role)).length;
    const label = count ? __("Save Changes ({0})", [count]) : __("Save Changes");
    this.page.set_primary_action(label, () => this.save_changes(), "check");
    this.page.btn_primary.prop("disabled", !count || !this.workspace?.editable);
  }

  open_workspace() {
    if (this.current_workspace) frappe.set_route("Form", "Workspace", this.current_workspace);
  }

  show_empty(message) {
    this.body.html(`<div class="wam-empty text-muted">${this.escape(message)}</div>`);
  }

  escape(value) {
    return $("<div>").text(value == null ? "" : String(value)).html();
  }
}
