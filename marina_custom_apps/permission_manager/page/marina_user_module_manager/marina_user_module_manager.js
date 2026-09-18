frappe.pages["marina-user-module-manager"].on_page_load = (wrapper) => {
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: __("User Module Access"),
    single_column: true,
  });

  frappe.breadcrumbs.add("Setup");
  wrapper.user_module_manager = new MarinaUserModuleManager(page);
};

class MarinaUserModuleManager {
  constructor(page) {
    this.page = page;
    this.modules = [];
    this.users = [];
    this.initial_availability = new Map();
    this.pending = new Set();
    this.current_module = null;
    this.globally_blocked = false;

    this.make_controls();
    this.make_body();
    this.bind_events();
    this.update_save_button();
    this.load_modules();
  }

  make_controls() {
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
      reqd: 1,
      change: () => this.handle_module_change(),
    });

    this.status_field = this.page.add_field({
      fieldname: "status",
      label: __("Status"),
      fieldtype: "Select",
      options: ["", "Available", "Blocked", "Module Profile", "Modified"],
      change: () => this.render(),
    });

    this.search_field = this.page.add_field({
      fieldname: "search",
      label: __("Search User"),
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
  }

  make_body() {
    this.body = $("<div class='mpm-root mum-root'></div>").appendTo(this.page.main);
  }

  bind_events() {
    this.body.on("change", ".mum-available", (event) => this.handle_user_change(event));
    this.body.on("change", ".mum-bulk-available", (event) => this.handle_bulk_change(event));
  }

  async load_modules() {
    this.show_empty(__("Loading installed modules..."));
    const response = await frappe.call({
      method: "marina_custom_apps.permission_manager.api.modules.get_modules",
      freeze: true,
      freeze_message: __("Loading installed modules..."),
    });

    this.modules = response.message.modules || [];
    const applications = [...new Set(this.modules.map((item) => item.app))];
    this.application_field.df.options = ["", ...applications];
    this.application_field.refresh();
    this.populate_module_options();
    this.show_empty(__("Select a Module to manage its availability for active users."));
  }

  handle_application_change() {
    const selected_module = this.module_field.get_value();
    this.populate_module_options();
    const available_modules = this.filtered_modules().map((item) => item.module);
    if (selected_module && !available_modules.includes(selected_module)) {
      this.module_field.set_value("");
    }
  }

  filtered_modules() {
    const application = this.application_field.get_value();
    return this.modules.filter((item) => !application || item.app === application);
  }

  populate_module_options() {
    const options = ["", ...this.filtered_modules().map((item) => item.module)];
    this.module_field.df.options = options;
    this.module_field.refresh();
  }

  async handle_module_change() {
    const next_module = this.module_field.get_value();
    if (next_module === this.current_module) return;

    if (this.pending.size && this.current_module) {
      frappe.confirm(
        __("Discard the unsaved module assignment changes?"),
        () => this.load_module(next_module),
        () => this.module_field.set_value(this.current_module)
      );
      return;
    }

    await this.load_module(next_module);
  }

  async load_module(module) {
    if (!module) {
      this.current_module = null;
      this.users = [];
      this.initial_availability.clear();
      this.pending.clear();
      this.update_save_button();
      this.show_empty(__("Select a Module to manage its availability for active users."));
      return;
    }

    const response = await frappe.call({
      method: "marina_custom_apps.permission_manager.api.modules.get_module_users",
      args: { module },
      freeze: true,
      freeze_message: __("Loading active users..."),
    });

    this.current_module = module;
    this.globally_blocked = Boolean(response.message.globally_blocked);
    this.users = response.message.users || [];
    this.initial_availability.clear();
    this.pending.clear();
    this.users.forEach((user) => {
      user.available = Boolean(user.available);
      this.initial_availability.set(user.user, user.available);
    });
    this.update_save_button();
    this.render();
  }

  visible_users() {
    const status = this.status_field.get_value();
    const search = (this.search_field.get_value() || "").trim().toLowerCase();

    return this.users.filter((user) => {
      if (status === "Available" && !user.available) return false;
      if (status === "Blocked" && user.available) return false;
      if (status === "Module Profile" && !user.module_profile) return false;
      if (status === "Modified" && !this.pending.has(user.user)) return false;
      if (
        search &&
        !`${user.full_name} ${user.user} ${user.module_profile || ""}`.toLowerCase().includes(search)
      ) {
        return false;
      }
      return true;
    });
  }

  render() {
    if (!this.current_module) {
      this.show_empty(__("Select a Module to manage its availability for active users."));
      return;
    }

    const users = this.visible_users();
    const available_count = this.users.filter((user) => user.available).length;
    const profile_count = this.users.filter((user) => user.module_profile).length;
    const global_warning = this.globally_blocked
      ? `<div class="alert alert-warning mum-warning">${__(
          "This module is blocked globally through Administrator. Individual assignments cannot be changed until the global block is removed."
        )}</div>`
      : "";
    const rows = users.length
      ? users.map((user) => this.render_user_row(user)).join("")
      : `<tr><td colspan="4" class="text-muted text-center p-4">${__(
          "No users match the current filters."
        )}</td></tr>`;

    this.body.html(`
      ${global_warning}
      <div class="mum-summary">
        <span><strong>${this.escape(this.current_module)}</strong></span>
        <span>${available_count} ${__("available")} / ${this.users.length} ${__("active users")}</span>
        <span>${profile_count} ${__("using Module Profiles")}</span>
      </div>
      <div class="mpm-table-wrap mum-table-wrap">
        <table class="table table-bordered mpm-table mum-table">
          <thead>
            <tr>
              <th class="mum-user-column">${__("User")}</th>
              <th class="mum-email-column">${__("Email / User ID")}</th>
              <th class="mum-profile-column">${__("Module Profile")}</th>
              <th class="mpm-check-cell">
                <label class="mum-bulk-label">
                  <input type="checkbox" class="mum-bulk-available"
                    ${this.globally_blocked || !users.length ? "disabled" : ""}>
                  <span>${__("Available")}</span>
                </label>
              </th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="text-muted mum-help">
        ${__(
          "Module availability controls Desk visibility only. Roles, DocType permissions, Workspace roles, and reports remain separate controls."
        )}
      </div>
    `);
    this.update_bulk_checkbox(users);
  }

  render_user_row(user) {
    const modified_class = this.pending.has(user.user) ? " mpm-row-modified" : "";
    const profile = user.module_profile
      ? `<span class="indicator-pill blue">${this.escape(user.module_profile)}</span>`
      : `<span class="text-muted">${__("Individual")}</span>`;

    return `
      <tr class="mum-user-row${modified_class}" data-user="${this.escape(user.user)}">
        <td class="mum-user-column">${this.escape(user.full_name)}</td>
        <td class="mum-email-column">${this.escape(user.user)}</td>
        <td class="mum-profile-column">${profile}</td>
        <td class="mpm-check-cell">
          <input type="checkbox" class="mum-available" data-user="${this.escape(user.user)}"
            ${user.available ? "checked" : ""} ${this.globally_blocked ? "disabled" : ""}>
        </td>
      </tr>
    `;
  }

  handle_user_change(event) {
    const input = $(event.currentTarget);
    const user = this.user_by_name(input.attr("data-user"));
    if (!user) return;

    user.available = input.is(":checked");
    this.update_pending(user);
    input.closest("tr").toggleClass("mpm-row-modified", this.pending.has(user.user));
    this.update_save_button();
    this.update_bulk_checkbox(this.visible_users());
  }

  handle_bulk_change(event) {
    const available = $(event.currentTarget).is(":checked");
    this.visible_users().forEach((user) => {
      user.available = available;
      this.update_pending(user);
    });
    this.update_save_button();
    this.render();
  }

  update_pending(user) {
    if (user.available === this.initial_availability.get(user.user)) {
      this.pending.delete(user.user);
    } else {
      this.pending.add(user.user);
    }
  }

  update_bulk_checkbox(users) {
    const checkbox = this.body.find(".mum-bulk-available");
    const available = users.filter((user) => user.available).length;
    checkbox
      .prop("checked", Boolean(users.length && available === users.length))
      .prop("indeterminate", available > 0 && available < users.length);
  }

  save_changes() {
    if (!this.pending.size) {
      frappe.show_alert({ message: __("There are no changes to save."), indicator: "blue" });
      return;
    }

    const changes = [...this.pending]
      .map((user_name) => this.user_by_name(user_name))
      .filter(Boolean)
      .map((user) => ({ user: user.user, available: user.available ? 1 : 0 }));
    const profile_users = changes.filter((change) => this.user_by_name(change.user).module_profile);
    let message = __("Apply module {0} changes to {1} users?", [
      `<strong>${this.escape(this.current_module)}</strong>`,
      changes.length,
    ]);
    if (profile_users.length) {
      message += `<br><br>${__(
        "{0} changed users currently use a Module Profile. They will become individually managed while their other module settings remain unchanged.",
        [profile_users.length]
      )}`;
    }

    frappe.confirm(message, async () => {
      const response = await frappe.call({
        method: "marina_custom_apps.permission_manager.api.modules.save_module_users",
        args: { module: this.current_module, changes },
        freeze: true,
        freeze_message: __("Saving module assignments..."),
      });
      frappe.show_alert({
        message: __("Updated {0} users.", [response.message.updated_users]),
        indicator: "green",
      });
      await this.load_module(this.current_module);
    });
  }

  discard_changes() {
    if (!this.pending.size) return;
    frappe.confirm(__("Discard all unsaved module assignment changes?"), () => {
      this.users.forEach((user) => {
        user.available = this.initial_availability.get(user.user);
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
    this.page.btn_primary.prop("disabled", !count || this.globally_blocked);
  }

  user_by_name(user_name) {
    return this.users.find((user) => user.user === user_name);
  }

  show_empty(message) {
    this.body.html(`<div class="mpm-empty text-muted">${this.escape(message)}</div>`);
  }

  escape(value) {
    return $("<div>").text(value == null ? "" : String(value)).html();
  }
}
