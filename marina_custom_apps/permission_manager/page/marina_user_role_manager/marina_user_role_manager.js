frappe.pages["marina-user-role-manager"].on_page_load = (wrapper) => {
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: __("User Role Manager"),
    single_column: true,
  });
  frappe.breadcrumbs.add("Setup");
  wrapper.user_role_manager = new MarinaUserRoleManager(page);
};

class MarinaUserRoleManager {
  constructor(page) {
    this.page = page;
    this.rows = [];
    this.original = new Map();
    this.pending = new Set();
    this.selected = "";
    this.profile = "";
    this.loading = false;
    this.suppress_view = false;
    this.make_controls();
    this.body = $("<div class='mrm-root'></div>").appendTo(page.main);
    this.body.on("change", ".mrm-assigned", (event) => this.toggle(event));
    this.body.on("change", ".mrm-bulk", (event) => this.bulk_toggle(event));
    this.update_save();
    this.load_catalogue();
  }

  make_controls() {
    this.view = this.page.add_field({
      fieldname: "view", label: __("Manage By"), fieldtype: "Select",
      options: ["Role → Users", "User → Roles"],
      change: () => this.switch_view(),
    });
    this.choice = this.page.add_field({
      fieldname: "choice", label: __("Role"), fieldtype: "Select", options: [""],
      change: () => this.change_choice(),
    });
    this.status = this.page.add_field({
      fieldname: "status", label: __("Status"), fieldtype: "Select",
      options: ["", "Assigned", "Unassigned", "Role Profile", "Modified"],
      change: () => this.render(),
    });
    this.search = this.page.add_field({
      fieldname: "search", label: __("Search"), fieldtype: "Data",
      change: () => this.render(),
    });
    this.page.add_inner_button(__("Discard Changes"), () => this.discard());
    this.page.add_inner_button(__("Dashboard"), () => frappe.set_route("permission-manager-dashboard"), __("Permission Manager"));
    this.page.add_inner_button(__("Role Permissions"), () => frappe.set_route("marina-permission-manager"), __("Permission Manager"));
    this.page.add_inner_button(__("User Modules"), () => frappe.set_route("marina-user-module-manager"), __("Permission Manager"));
    this.page.add_inner_button(__("User Permissions"), () => frappe.set_route("marina-user-permission-manager"), __("Permission Manager"));
  }

  is_user_view() { return this.view.get_value() === "User → Roles"; }

  async load_catalogue() {
    this.empty(__("Loading users and roles..."));
    const [roles, users] = await Promise.all([
      frappe.call({ method: "marina_custom_apps.permission_manager.api.user_roles.get_roles_catalogue" }),
      frappe.call({ method: "marina_custom_apps.permission_manager.api.user_roles.get_role_users_list" }),
    ]);
    this.roles = roles.message.roles || [];
    this.users = users.message.users || [];
    this.update_options();
    this.empty(__("Select a Role to manage its users."));
  }

  update_options() {
    this.choice.df.label = this.is_user_view() ? __("User") : __("Role");
    this.choice.df.options = ["", ...(this.is_user_view()
      ? this.users.map((user) => user.user) : this.roles)];
    this.choice.refresh();
    this.status.df.options = this.is_user_view()
      ? ["", "Assigned", "Unassigned", "Modified"]
      : ["", "Assigned", "Unassigned", "Role Profile", "Modified"];
    this.status.set_value("");
    this.status.refresh();
  }

  switch_view() {
    if (this.suppress_view) return;
    const action = () => {
      this.selected = "";
      this.rows = [];
      this.original.clear();
      this.pending.clear();
      this.profile = "";
      this.update_options();
      this.choice.set_value("");
      this.update_save();
      this.empty(this.is_user_view()
        ? __("Select a User to manage their direct roles.")
        : __("Select a Role to manage its users."));
    };
    if (this.pending.size) {
      frappe.confirm(__("Discard unsaved role changes?"), action, () => {
        this.suppress_view = true;
        this.view.set_value(this.is_user_view() ? "Role → Users" : "User → Roles");
        this.suppress_view = false;
      });
    } else action();
  }

  change_choice() {
    const next = this.choice.get_value();
    if (next === this.selected) return;
    if (this.pending.size) {
      frappe.confirm(__("Discard unsaved role changes?"), () => this.load(next), () => this.choice.set_value(this.selected));
    } else this.load(next);
  }

  async load(value) {
    this.selected = value;
    this.rows = [];
    this.pending.clear();
    this.original.clear();
    this.profile = "";
    this.update_save();
    if (!value) {
      this.empty(__("Select a Role or User to manage assignments."));
      return;
    }
    this.loading = true;
    this.empty(__("Loading assignments..."));
    try {
      const response = await frappe.call({
        method: `marina_custom_apps.permission_manager.api.user_roles.${this.is_user_view() ? "get_user_roles" : "get_role_users"}`,
        args: this.is_user_view() ? { user: value } : { role: value },
      });
      if (this.selected !== value) return;
      this.profile = response.message.role_profile || "";
      this.rows = response.message[this.is_user_view() ? "roles" : "users"] || [];
      this.rows.forEach((row) => {
        row.assigned = Boolean(row.assigned);
        this.original.set(this.row_key(row), row.assigned);
      });
      this.loading = false;
      this.render();
    } finally { this.loading = false; }
  }

  row_key(row) { return this.is_user_view() ? row.role : row.user; }
  row_for(key) { return this.rows.find((row) => this.row_key(row) === key); }

  visible() {
    const status = this.status.get_value();
    const search = (this.search.get_value() || "").trim().toLowerCase();
    return this.rows.filter((row) => {
      const key = this.row_key(row);
      if (status === "Assigned" && !row.assigned) return false;
      if (status === "Unassigned" && row.assigned) return false;
      if (status === "Role Profile" && !row.role_profile) return false;
      if (status === "Modified" && !this.pending.has(key)) return false;
      return !search || `${key} ${row.full_name || ""} ${row.role_profile || ""}`.toLowerCase().includes(search);
    });
  }

  render() {
    if (!this.selected || this.loading) return;
    const rows = this.visible();
    const assigned = this.rows.filter((row) => row.assigned).length;
    const profile_help = this.is_user_view() && this.profile
      ? `<div class="alert alert-info">${__("This user's roles are managed by Role Profile {0}. Change the profile or the User record to edit assignments.", [this.escape(this.profile)])}</div>`
      : "";
    const html = rows.map((row) => {
      const key = this.row_key(row);
      const profile = row.role_profile
        ? `<span class="indicator-pill blue">${this.escape(row.role_profile)}</span>`
        : `<span class="text-muted">${__("Direct")}</span>`;
      return `<tr class="${this.pending.has(key) ? "mrm-modified" : ""}">
        <td>${this.escape(this.is_user_view() ? row.role : row.full_name)}</td>
        <td>${this.is_user_view() ? "" : this.escape(row.user)}</td>
        <td>${this.is_user_view() ? (this.profile ? this.escape(this.profile) : __("Direct")) : profile}</td>
        <td class="mrm-check"><input type="checkbox" class="mrm-assigned" data-key="${this.escape(key)}"
          ${row.assigned ? "checked" : ""} ${row.editable ? "" : "disabled"}></td>
      </tr>`;
    }).join("") || `<tr><td colspan="4" class="text-center text-muted p-4">${__("No matching assignments.")}</td></tr>`;
    this.body.html(`${profile_help}
      <div class="mrm-summary"><strong>${this.escape(this.selected)}</strong>
        <span>${assigned} ${__("assigned")} / ${this.rows.length} ${__("available")}</span>
        <span>${this.pending.size} ${__("unsaved changes")}</span></div>
      <div class="mrm-table-wrap"><table class="table table-bordered mrm-table">
        <thead><tr><th>${this.is_user_view() ? __("Role") : __("User")}</th>
          <th>${this.is_user_view() ? "" : __("User ID")}</th><th>${__("Role Profile")}</th>
          <th class="mrm-check">${this.is_user_view() ? __("Assigned") : `<label><input type="checkbox" class="mrm-bulk"> ${__("Assigned")}</label>`}</th>
        </tr></thead><tbody>${html}</tbody></table></div>
      <div class="mrm-help text-muted">${__("Role Profile assignments are read-only here. Direct role edits use Frappe's User validation and update permissions after saving.")}</div>`);
    if (!this.is_user_view()) this.update_bulk(rows);
  }

  toggle(event) {
    const input = $(event.currentTarget);
    const row = this.row_for(input.attr("data-key"));
    if (!row || !row.editable) return;
    row.assigned = input.is(":checked");
    this.track(row);
    this.update_save();
    this.render();
  }

  bulk_toggle(event) {
    const assign = $(event.currentTarget).is(":checked");
    this.visible().filter((row) => row.editable).forEach((row) => {
      row.assigned = assign;
      this.track(row);
    });
    this.update_save();
    this.render();
  }

  track(row) {
    const key = this.row_key(row);
    if (row.assigned === this.original.get(key)) this.pending.delete(key);
    else this.pending.add(key);
  }

  update_bulk(rows) {
    const editable = rows.filter((row) => row.editable);
    const assigned = editable.filter((row) => row.assigned).length;
    this.body.find(".mrm-bulk")
      .prop("disabled", !editable.length)
      .prop("checked", Boolean(editable.length && assigned === editable.length))
      .prop("indeterminate", assigned > 0 && assigned < editable.length);
  }

  update_save() {
    const count = this.pending.size;
    this.page.set_primary_action(count ? __("Save Changes ({0})", [count]) : __("Save Changes"), () => this.save(), "check");
    this.page.btn_primary.prop("disabled", !count);
  }

  save() {
    if (!this.pending.size) return;
    const view_user = this.is_user_view();
    const selection = this.selected;
    const count = this.pending.size;
    frappe.confirm(__("Save {0} role assignment changes?", [count]), async () => {
      const method = `marina_custom_apps.permission_manager.api.user_roles.${view_user ? "save_user_roles" : "save_role_users"}`;
      const args = view_user ? {
        user: selection,
        roles: this.rows.filter((row) => row.assigned).map((row) => row.role),
        expected: this.rows.filter((row) => this.original.get(row.role)).map((row) => row.role),
      } : {
        role: selection,
        changes: [...this.pending].map((key) => ({
          user: key, assigned: this.row_for(key).assigned ? 1 : 0,
          expected: this.original.get(key) ? 1 : 0,
        })),
      };
      const response = await frappe.call({ method, args, freeze: true, freeze_message: __("Saving user roles...") });
      frappe.show_alert({ message: __("Updated {0} users.", [response.message.updated_users]), indicator: "green" });
      await this.load(selection);
    });
  }

  discard() {
    if (!this.pending.size) return;
    frappe.confirm(__("Discard all unsaved role changes?"), () => {
      this.rows.forEach((row) => { row.assigned = this.original.get(this.row_key(row)); });
      this.pending.clear();
      this.update_save();
      this.render();
    });
  }

  empty(message) { this.body.html(`<div class="mrm-empty text-muted">${this.escape(message)}</div>`); }
  escape(value) { return $("<div>").text(value == null ? "" : String(value)).html(); }
}
