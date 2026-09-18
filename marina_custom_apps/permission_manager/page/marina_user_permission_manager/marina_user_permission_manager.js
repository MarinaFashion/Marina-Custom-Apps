frappe.pages["marina-user-permission-manager"].on_page_load = (wrapper) => {
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: __("Bulk User Permissions"),
    single_column: true,
  });

  frappe.breadcrumbs.add("Setup");
  wrapper.user_permission_manager = new MarinaUserPermissionManager(page);
};

class MarinaUserPermissionManager {
  constructor(page) {
    this.page = page;
    this.current_rule = null;
    this.users = [];
    this.initial_assigned = new Map();
    this.pending = new Set();
    this.suppress_changes = false;
    this.default_touched = false;
    this.loaded_default = false;
    this.current_value_rule = null;
    this.selected_user = null;
    this.values = [];
    this.initial_values = new Map();
    this.value_pending = new Set();
    this.values_truncated = false;
    this.value_limit = 0;
    this.active_mode = "Permissions for User";

    this.make_controls();
    this.make_body();
    this.bind_events();
    this.configure_mode();
    this.show_mode_empty();
    this.update_save_button();
  }

  make_controls() {
    this.mode_field = this.page.add_field({
      fieldname: "management_mode",
      label: __("Management Mode"),
      fieldtype: "Select",
      options: ["Permissions for User", "Users for Permission"],
      default: "Permissions for User",
      reqd: 1,
      change: () => this.handle_mode_change(),
    });

    this.user_field = this.page.add_field({
      fieldname: "user",
      label: __("User"),
      fieldtype: "Link",
      options: "User",
      reqd: 1,
      get_query: () => ({
        filters: { user_type: "System User", name: ["not in", ["Administrator", "Guest"]] },
      }),
      change: () => this.handle_user_selection_change(),
    });

    this.allow_field = this.page.add_field({
      fieldname: "allow",
      label: __("Allow"),
      fieldtype: "Link",
      options: "DocType",
      reqd: 1,
      get_query: () => ({ filters: { issingle: 0, istable: 0 } }),
      change: () => this.handle_allow_change(),
    });

    this.value_field = this.page.add_field({
      fieldname: "for_value",
      label: __("For Value"),
      fieldtype: "Link",
      options: "",
      reqd: 1,
      change: () => this.handle_identity_change(),
    });

    this.apply_all_field = this.page.add_field({
      fieldname: "apply_to_all_doctypes",
      label: __("Apply To All Document Types"),
      fieldtype: "Check",
      default: 1,
      change: () => this.handle_scope_change(),
    });

    this.applicable_field = this.page.add_field({
      fieldname: "applicable_for",
      label: __("Applicable For"),
      fieldtype: "Link",
      options: "DocType",
      get_query: () => ({
        query: "frappe.core.doctype.user_permission.user_permission.get_applicable_for_doctype_list",
        doctype: this.allow_field.get_value(),
      }),
      change: () => this.handle_identity_change(),
    });

    this.default_field = this.page.add_field({
      fieldname: "is_default",
      label: __("Is Default"),
      fieldtype: "Check",
      default: 0,
      change: () => this.handle_default_change(),
    });

    this.user_status_field = this.page.add_field({
      fieldname: "user_status",
      label: __("User Status"),
      fieldtype: "Select",
      options: ["All", "Active", "Inactive"],
      default: "Active",
      change: () => this.render(),
    });

    this.status_field = this.page.add_field({
      fieldname: "status",
      label: __("Status"),
      fieldtype: "Select",
      options: ["", "Assigned", "Unassigned", "Other Permissions", "Default Conflict", "Modified"],
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
      __("User Permission List"),
      () => frappe.set_route("List", "User Permission"),
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
      __("Workspaces"),
      () => frappe.set_route("marina-workspace-access-manager"),
      __("Permission Manager")
    );
    this.page.add_inner_button(
      __("Pages and Reports"),
      () => frappe.set_route("marina-page-report-permission-manager"),
      __("Permission Manager")
    );
  }

  make_body() {
    this.body = $("<div class='mpm-root upm-root'></div>").appendTo(this.page.main);
    this.update_scope_controls();
  }

  bind_events() {
    this.body.on("change", ".upm-assigned", (event) => this.handle_user_change(event));
    this.body.on("change", ".upm-bulk-assigned", (event) => this.handle_bulk_change(event));
    this.body.on("click", ".upm-permission-link", (event) => this.handle_permission_link(event));
    this.body.on("change", ".upm-value-assigned", (event) => this.handle_value_assignment(event));
    this.body.on("change", ".upm-value-default", (event) => this.handle_value_default(event));
    this.body.on("change", ".upm-bulk-value", (event) => this.handle_bulk_value(event));
    this.body.on("click", ".upm-value-link", (event) => this.handle_value_link(event));
  }

  is_value_mode() {
    return this.mode_field.get_value() !== "Users for Permission";
  }

  has_pending() {
    return this.value_pending.size > 0 || this.pending.size > 0;
  }

  apply_all_enabled() {
    const value = this.apply_all_field.get_value();
    return value === true || value === 1 || value === "1" || value === "true";
  }

  handle_mode_change() {
    if (this.suppress_changes) return;
    const requested_mode = this.mode_field.get_value();
    const switch_mode = () => {
      this.clear_loaded_rule();
      this.clear_loaded_values();
      this.active_mode = requested_mode;
      this.configure_mode();
      this.show_mode_empty();
      this.update_save_button();
    };
    if (this.has_pending()) {
      frappe.confirm(
        __("Discard the unsaved User Permission changes?"),
        switch_mode,
        () => this.with_suppressed_changes(() => this.mode_field.set_value(this.active_mode))
      );
    } else {
      switch_mode();
    }
  }

  configure_mode() {
    const value_mode = this.is_value_mode();
    this.user_field.toggle(value_mode);
    this.user_field.df.reqd = value_mode ? 1 : 0;
    this.value_field.toggle(!value_mode);
    this.value_field.df.reqd = value_mode ? 0 : 1;
    this.default_field.toggle(!value_mode);
    this.user_status_field.toggle(!value_mode);
    this.status_field.df.options = value_mode
      ? ["", "Assigned", "Unassigned", "Default", "Missing Document", "Modified"]
      : ["", "Assigned", "Unassigned", "Other Permissions", "Default Conflict", "Modified"];
    this.status_field.set_value("");
    this.status_field.refresh();
    this.search_field.df.label = value_mode ? __("Search Value") : __("Search User");
    this.search_field.set_value("");
    this.search_field.refresh();
    this.update_scope_controls();
  }

  show_mode_empty() {
    this.show_empty(
      this.is_value_mode()
        ? __("Select a User and Allow document type to manage permitted values.")
        : __("Select Allow and For Value to load Desk users.")
    );
  }

  async with_suppressed_changes(callback) {
    this.suppress_changes = true;
    try {
      await callback();
    } finally {
      this.suppress_changes = false;
    }
  }

  handle_allow_change() {
    if (this.suppress_changes) return;
    const proceed = async () => {
      const allow = this.allow_field.get_value();
      if (this.is_value_mode()) this.clear_loaded_values();
      else this.clear_loaded_rule();
      await this.with_suppressed_changes(async () => {
        this.value_field.df.options = allow || "";
        await this.value_field.set_value("");
        this.value_field.refresh();
        await this.applicable_field.set_value("");
      });
      if (this.is_value_mode()) await this.load_user_values();
    };
    this.confirm_current_change(proceed);
  }

  handle_scope_change() {
    if (this.suppress_changes) return;
    const proceed = async () => {
      this.update_scope_controls();
      if (this.apply_all_enabled()) {
        await this.with_suppressed_changes(() => this.applicable_field.set_value(""));
      }
      if (this.is_value_mode()) await this.load_user_values();
      else await this.load_from_controls();
    };
    this.confirm_current_change(proceed);
  }

  handle_identity_change() {
    if (this.suppress_changes) return;
    this.confirm_current_change(() => (
      this.is_value_mode() ? this.load_user_values() : this.load_from_controls()
    ));
  }

  handle_user_selection_change() {
    if (this.suppress_changes || !this.is_value_mode()) return;
    this.confirm_current_change(() => this.load_user_values());
  }

  handle_default_change() {
    if (this.suppress_changes || !this.current_rule) return;
    this.default_touched = true;
    this.users.forEach((user) => this.update_pending(user));
    this.update_save_button();
    this.render();
  }

  confirm_current_change(proceed) {
    if (!this.has_pending()) {
      proceed();
      return;
    }
    frappe.confirm(
      __("Discard the unsaved User Permission changes?"),
      proceed,
      () => (
        this.is_value_mode()
          ? this.restore_value_rule_controls()
          : this.restore_current_rule_controls()
      )
    );
  }

  update_scope_controls() {
    const apply_all = this.apply_all_enabled();
    this.applicable_field.toggle(!apply_all);
    this.applicable_field.df.reqd = apply_all ? 0 : 1;
    this.applicable_field.refresh();
  }

  rule_from_controls() {
    return {
      allow: this.allow_field.get_value(),
      for_value: this.value_field.get_value(),
      apply_to_all_doctypes: this.apply_all_enabled() ? 1 : 0,
      applicable_for: this.apply_all_enabled() ? "" : this.applicable_field.get_value(),
    };
  }

  rule_is_complete(rule) {
    return Boolean(
      rule.allow && rule.for_value && (rule.apply_to_all_doctypes || rule.applicable_for)
    );
  }

  value_rule_from_controls() {
    return {
      user: this.user_field.get_value(),
      allow: this.allow_field.get_value(),
      apply_to_all_doctypes: this.apply_all_enabled() ? 1 : 0,
      applicable_for: this.apply_all_enabled() ? "" : this.applicable_field.get_value(),
    };
  }

  value_rule_is_complete(rule) {
    return Boolean(rule.user && rule.allow && (rule.apply_to_all_doctypes || rule.applicable_for));
  }

  async load_user_values() {
    const rule = this.value_rule_from_controls();
    if (!this.value_rule_is_complete(rule)) {
      this.clear_loaded_values();
      return;
    }

    const response = await frappe.call({
      method: "marina_custom_apps.permission_manager.api.user_permissions.get_user_permission_values",
      args: rule,
      freeze: true,
      freeze_message: __("Loading User Permissions..."),
    });
    this.selected_user = response.message.user;
    this.current_value_rule = response.message.rule;
    this.values = response.message.values || [];
    this.values_truncated = Boolean(response.message.truncated);
    this.value_limit = response.message.limit || 0;
    this.initial_values.clear();
    this.value_pending.clear();
    this.values.forEach((value) => {
      value.assigned = Boolean(value.assigned);
      value.is_default = Boolean(value.is_default);
      this.initial_values.set(value.for_value, {
        assigned: value.assigned,
        is_default: value.is_default,
      });
    });
    this.update_save_button();
    this.render();
  }

  clear_loaded_values() {
    this.current_value_rule = null;
    this.selected_user = null;
    this.values = [];
    this.initial_values.clear();
    this.value_pending.clear();
    this.values_truncated = false;
    this.value_limit = 0;
    this.update_save_button();
    if (this.is_value_mode()) {
      this.show_empty(__("Select a User and Allow document type to manage permitted values."));
    }
  }

  async restore_value_rule_controls() {
    if (!this.current_value_rule || !this.selected_user) return;
    await this.with_suppressed_changes(async () => {
      await this.user_field.set_value(this.selected_user.name);
      await this.allow_field.set_value(this.current_value_rule.allow);
      await this.apply_all_field.set_value(this.current_value_rule.apply_to_all_doctypes ? 1 : 0);
      await this.applicable_field.set_value(this.current_value_rule.applicable_for || "");
      this.update_scope_controls();
    });
  }

  async load_from_controls() {
    const rule = this.rule_from_controls();
    if (!this.rule_is_complete(rule)) {
      this.clear_loaded_rule();
      return;
    }

    const response = await frappe.call({
      method: "marina_custom_apps.permission_manager.api.user_permissions.get_user_permission_users",
      args: rule,
      freeze: true,
      freeze_message: __("Loading User Permissions..."),
    });
    this.current_rule = response.message.rule;
    this.users = response.message.users || [];
    this.initial_assigned.clear();
    this.pending.clear();
    this.users.forEach((user) => {
      user.assigned = Boolean(user.assigned);
      user.is_default = Boolean(user.is_default);
      this.initial_assigned.set(user.user, user.assigned);
    });
    const assigned_users = this.users.filter((user) => user.assigned);
    this.loaded_default = Boolean(
      assigned_users.length && assigned_users.every((user) => user.is_default)
    );
    this.default_touched = false;
    await this.with_suppressed_changes(() => this.default_field.set_value(this.loaded_default ? 1 : 0));
    this.update_save_button();
    this.render();
  }

  clear_loaded_rule() {
    this.current_rule = null;
    this.users = [];
    this.initial_assigned.clear();
    this.pending.clear();
    this.default_touched = false;
    this.update_save_button();
    this.show_empty(__("Select Allow and For Value to load Desk users."));
  }

  async restore_current_rule_controls() {
    if (!this.current_rule) return;
    await this.with_suppressed_changes(async () => {
      await this.allow_field.set_value(this.current_rule.allow);
      this.value_field.df.options = this.current_rule.allow;
      await this.value_field.set_value(this.current_rule.for_value);
      this.value_field.refresh();
      await this.apply_all_field.set_value(this.current_rule.apply_to_all_doctypes ? 1 : 0);
      await this.applicable_field.set_value(this.current_rule.applicable_for || "");
      this.update_scope_controls();
    });
  }

  visible_users() {
    const status = this.status_field.get_value();
    const user_status = this.user_status_field.get_value() || "Active";
    const search = (this.search_field.get_value() || "").trim().toLowerCase();
    return this.users.filter((user) => {
      if (user_status === "Active" && !user.enabled) return false;
      if (user_status === "Inactive" && user.enabled) return false;
      if (status === "Assigned" && !user.assigned) return false;
      if (status === "Unassigned" && user.assigned) return false;
      if (status === "Other Permissions" && !user.other_permissions) return false;
      if (status === "Default Conflict" && !user.other_default) return false;
      if (status === "Modified" && !this.pending.has(user.user)) return false;
      return !search || `${user.full_name} ${user.user}`.toLowerCase().includes(search);
    });
  }

  render() {
    if (this.is_value_mode()) this.render_values_mode();
    else this.render_users_mode();
  }

  render_users_mode() {
    if (!this.current_rule) {
      this.show_empty(__("Select Allow and For Value to load Desk users."));
      return;
    }
    const users = this.visible_users();
    const assigned = this.users.filter((user) => user.assigned).length;
    const inactive_assigned = this.users.filter((user) => !user.enabled && user.assigned).length;
    const desired_default = Boolean(this.default_field.get_value());
    const scope = this.current_rule.apply_to_all_doctypes
      ? __("All linked document types")
      : this.current_rule.applicable_for;
    const rows = users.length
      ? users.map((user) => this.render_user(user, desired_default)).join("")
      : `<tr><td colspan="6" class="text-muted text-center p-4">${__("No users match the current filters.")}</td></tr>`;

    this.body.html(`
      <section class="upm-summary">
        <div><strong>${this.escape(this.current_rule.allow)}:</strong> ${this.escape(this.current_rule.for_value)}</div>
        <div class="upm-metrics">
          <span>${this.escape(scope)}</span>
          <span>${assigned} ${__("assigned")} / ${this.users.length} ${__("Desk users")}</span>
          <span>${inactive_assigned} ${__("inactive users with this rule")}</span>
          <span>${desired_default ? __("Default value") : __("Not default")}</span>
        </div>
      </section>
      <div class="alert alert-info upm-help">
        ${__("This screen changes only the exact rule shown above. Other User Permissions belonging to each user are preserved.")}
      </div>
      <div class="upm-table-wrap">
        <table class="table table-bordered upm-table">
          <colgroup><col style="width:23%"><col style="width:27%"><col style="width:10%"><col style="width:12%"><col style="width:18%"><col style="width:10%"></colgroup>
          <thead><tr>
            <th>${__("User")}</th>
            <th>${__("Email / User ID")}</th>
            <th>${__("User Status")}</th>
            <th>${__("Other Rules")}</th>
            <th>${__("Default Status")}</th>
            <th class="upm-check-cell"><label><input type="checkbox" class="upm-bulk-assigned"> ${__("Assigned")}</label></th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `);
    this.update_bulk_checkbox(users);
  }

  visible_values() {
    const status = this.status_field.get_value();
    const search = (this.search_field.get_value() || "").trim().toLowerCase();
    return this.values.filter((value) => {
      if (status === "Assigned" && !value.assigned) return false;
      if (status === "Unassigned" && value.assigned) return false;
      if (status === "Default" && !value.is_default) return false;
      if (status === "Missing Document" && !value.missing) return false;
      if (status === "Modified" && !this.value_pending.has(value.for_value)) return false;
      return !search || `${value.label} ${value.for_value}`.toLowerCase().includes(search);
    });
  }

  render_values_mode() {
    if (!this.current_value_rule || !this.selected_user) {
      this.show_empty(__("Select a User and Allow document type to manage permitted values."));
      return;
    }
    const values = this.visible_values();
    const assigned = this.values.filter((value) => value.assigned).length;
    const scope = this.current_value_rule.apply_to_all_doctypes
      ? __("All linked document types")
      : this.current_value_rule.applicable_for;
    const rows = values.length
      ? values.map((value) => this.render_value(value)).join("")
      : `<tr><td colspan="5" class="text-muted text-center p-4">${__("No values match the current filters.")}</td></tr>`;
    const inactive_warning = this.selected_user.enabled ? "" : `
      <div class="alert alert-warning upm-help">
        ${__("This user is inactive. Existing permissions can be removed, but new permissions cannot be assigned.")}
      </div>`;
    const truncated_warning = this.values_truncated ? `
      <div class="alert alert-warning upm-help">
        ${__("Only the first {0} available values are shown. Existing assigned values remain visible and removable.", [this.value_limit])}
      </div>` : "";

    this.body.html(`
      <section class="upm-summary">
        <div>
          <strong>${this.escape(this.selected_user.full_name)}</strong>
          <span class="indicator-pill ${this.selected_user.enabled ? "green" : "gray"}">${this.selected_user.enabled ? __("Active") : __("Inactive")}</span>
          <div class="text-muted">${this.escape(this.selected_user.name)}</div>
        </div>
        <div class="upm-metrics">
          <span>${this.escape(this.current_value_rule.allow)}</span>
          <span>${this.escape(scope)}</span>
          <span>${assigned} ${__("assigned")} / ${this.values.length} ${__("available values")}</span>
        </div>
      </section>
      ${inactive_warning}
      ${truncated_warning}
      <div class="alert alert-info upm-help">
        ${__("Saving reconciles only this user, Allow document type, and scope. All unrelated User Permissions are preserved.")}
      </div>
      <div class="upm-table-wrap">
        <table class="table table-bordered upm-table">
          <colgroup><col style="width:31%"><col style="width:27%"><col style="width:20%"><col style="width:10%"><col style="width:12%"></colgroup>
          <thead><tr>
            <th>${__("Value")}</th>
            <th>${__("Technical Name")}</th>
            <th>${__("User Permission Record")}</th>
            <th>${__("Default")}</th>
            <th class="upm-check-cell"><label><input type="checkbox" class="upm-bulk-value"> ${__("Assigned")}</label></th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `);
    this.update_bulk_value_checkbox(values);
  }

  render_value(value) {
    const modified = this.value_pending.has(value.for_value) ? " upm-row-modified" : "";
    const missing = value.missing
      ? ` <span class="indicator-pill orange">${__("Missing document")}</span>`
      : "";
    const value_link = value.missing
      ? this.escape(value.label)
      : `<a class="upm-value-link" href="/app/${frappe.router.slug(this.current_value_rule.allow)}/${encodeURIComponent(value.for_value)}" data-value="${this.escape(value.for_value)}">${this.escape(value.label)} ↗</a>`;
    const permission_link = value.permission
      ? `<a class="upm-permission-link" href="/app/user-permission/${encodeURIComponent(value.permission)}" data-name="${this.escape(value.permission)}">${this.escape(value.permission)} ↗</a>`
      : `<span class="text-muted">${__("Will be created on save")}</span>`;
    const cannot_assign = !this.selected_user.enabled && !this.initial_values.get(value.for_value)?.assigned;
    return `
      <tr class="upm-value-row${modified}" data-value="${this.escape(value.for_value)}">
        <td>${value_link}${missing}</td>
        <td>${this.escape(value.for_value)}</td>
        <td>${value.assigned ? permission_link : `<span class="text-muted">—</span>`}</td>
        <td class="upm-check-cell"><input type="checkbox" class="upm-value-default"
          data-value="${this.escape(value.for_value)}" ${value.is_default ? "checked" : ""}
          ${!value.assigned || cannot_assign ? "disabled" : ""}></td>
        <td class="upm-check-cell"><input type="checkbox" class="upm-value-assigned"
          data-value="${this.escape(value.for_value)}" ${value.assigned ? "checked" : ""}
          ${cannot_assign ? "disabled" : ""}></td>
      </tr>`;
  }

  render_user(user, desired_default) {
    const modified = this.pending.has(user.user) ? " upm-row-modified" : "";
    const existing_link = user.permission
      ? `<a class="upm-permission-link" href="/app/user-permission/${encodeURIComponent(user.permission)}" data-name="${this.escape(user.permission)}">${__("Open rule")} ↗</a>`
      : `<span class="text-muted">—</span>`;
    let default_status = `<span class="text-muted">—</span>`;
    if (user.assigned) {
      default_status = desired_default
        ? `<span class="indicator-pill ${user.other_default ? "red" : "green"}">${user.other_default ? __("Conflict: {0}", [this.escape(user.other_default)]) : __("Will be default")}</span>`
        : `<span class="indicator-pill gray">${__("Not default")}</span>`;
    }
    return `
      <tr class="upm-user-row${modified}" data-user="${this.escape(user.user)}">
        <td>${this.escape(user.full_name)}</td>
        <td>${this.escape(user.user)}</td>
        <td><span class="indicator-pill ${user.enabled ? "green" : "gray"}">${user.enabled ? __("Active") : __("Inactive")}</span></td>
        <td>${user.other_permissions} ${existing_link}</td>
        <td>${default_status}</td>
        <td class="upm-check-cell"><input type="checkbox" class="upm-assigned"
          data-user="${this.escape(user.user)}" ${user.assigned ? "checked" : ""}
          ${!user.enabled && !user.assigned ? "disabled" : ""}></td>
      </tr>`;
  }

  handle_user_change(event) {
    const input = $(event.currentTarget);
    const user = this.users.find((item) => item.user === input.attr("data-user"));
    if (!user) return;
    user.assigned = input.is(":checked");
    this.update_pending(user);
    this.update_save_button();
    this.render();
  }

  handle_bulk_change(event) {
    const assigned = $(event.currentTarget).is(":checked");
    this.visible_users().forEach((user) => {
      if (assigned && !user.enabled) return;
      user.assigned = assigned;
      this.update_pending(user);
    });
    this.update_save_button();
    this.render();
  }

  update_pending(user) {
    const desired_default = Boolean(this.default_field.get_value());
    const assignment_changed = user.assigned !== this.initial_assigned.get(user.user);
    const default_changed =
      this.default_touched && user.assigned && user.is_default !== desired_default;
    if (assignment_changed || default_changed) this.pending.add(user.user);
    else this.pending.delete(user.user);
  }

  update_bulk_checkbox(users) {
    const selected = users.filter((user) => user.assigned).length;
    const removable_or_assignable = users.filter((user) => user.enabled || user.assigned);
    this.body.find(".upm-bulk-assigned")
      .prop("checked", Boolean(users.length && selected === users.length))
      .prop("indeterminate", selected > 0 && selected < users.length)
      .prop("disabled", !removable_or_assignable.length);
  }

  handle_value_assignment(event) {
    const input = $(event.currentTarget);
    const value = this.values.find((item) => item.for_value === input.attr("data-value"));
    if (!value) return;
    value.assigned = input.is(":checked");
    if (!value.assigned) value.is_default = false;
    this.update_value_pending(value);
    this.update_save_button();
    this.render();
  }

  handle_value_default(event) {
    const input = $(event.currentTarget);
    const value = this.values.find((item) => item.for_value === input.attr("data-value"));
    if (!value) return;
    const make_default = input.is(":checked");
    if (make_default) {
      this.values.forEach((item) => {
        item.is_default = item.for_value === value.for_value;
        if (item.is_default) item.assigned = true;
        this.update_value_pending(item);
      });
    } else {
      value.is_default = false;
      this.update_value_pending(value);
    }
    this.update_save_button();
    this.render();
  }

  handle_bulk_value(event) {
    const assigned = $(event.currentTarget).is(":checked");
    this.visible_values().forEach((value) => {
      const was_assigned = Boolean(this.initial_values.get(value.for_value)?.assigned);
      if (assigned && !this.selected_user.enabled && !was_assigned) return;
      value.assigned = assigned;
      if (!assigned) value.is_default = false;
      this.update_value_pending(value);
    });
    this.update_save_button();
    this.render();
  }

  update_value_pending(value) {
    const initial = this.initial_values.get(value.for_value) || {
      assigned: false,
      is_default: false,
    };
    if (value.assigned !== initial.assigned || value.is_default !== initial.is_default) {
      this.value_pending.add(value.for_value);
    } else {
      this.value_pending.delete(value.for_value);
    }
  }

  update_bulk_value_checkbox(values) {
    const selected = values.filter((value) => value.assigned).length;
    const manageable = values.filter((value) => (
      this.selected_user.enabled || this.initial_values.get(value.for_value)?.assigned
    ));
    this.body.find(".upm-bulk-value")
      .prop("checked", Boolean(values.length && selected === values.length))
      .prop("indeterminate", selected > 0 && selected < values.length)
      .prop("disabled", !manageable.length);
  }

  save_changes() {
    if (this.is_value_mode()) {
      this.save_value_changes();
      return;
    }
    if (!this.pending.size || !this.current_rule) {
      frappe.show_alert({ message: __("There are no changes to save."), indicator: "blue" });
      return;
    }
    const desired_default = Boolean(this.default_field.get_value());
    const conflicts = this.users.filter(
      (user) => this.pending.has(user.user) && user.assigned && desired_default && user.other_default
    );
    if (conflicts.length) {
      frappe.msgprint({
        title: __("Default User Permission Conflict"),
        indicator: "red",
        message: __("Remove the existing default permission for these users before saving: {0}", [
          conflicts.slice(0, 10).map((user) => this.escape(user.full_name)).join(", "),
        ]),
      });
      return;
    }
    const changes = [...this.pending].map((user_name) => {
      const user = this.users.find((item) => item.user === user_name);
      return { user: user.user, assigned: user.assigned ? 1 : 0 };
    });
    frappe.confirm(
      __("Apply this User Permission rule to {0} changed users?", [changes.length]),
      async () => {
        const response = await frappe.call({
          method: "marina_custom_apps.permission_manager.api.user_permissions.save_user_permission_users",
          args: {
            ...this.current_rule,
            is_default: desired_default ? 1 : 0,
            changes,
          },
          freeze: true,
          freeze_message: __("Saving User Permissions..."),
        });
        const result = response.message;
        frappe.show_alert({
          message: __("Created {0}, updated {1}, deleted {2} User Permissions.", [
            result.created, result.updated, result.deleted,
          ]),
          indicator: "green",
        });
        await this.load_from_controls();
      }
    );
  }

  save_value_changes() {
    if (!this.value_pending.size || !this.current_value_rule || !this.selected_user) {
      frappe.show_alert({ message: __("There are no changes to save."), indicator: "blue" });
      return;
    }
    const changes = [...this.value_pending].map((for_value) => {
      const value = this.values.find((item) => item.for_value === for_value);
      return {
        for_value: value.for_value,
        assigned: value.assigned ? 1 : 0,
        is_default: value.is_default ? 1 : 0,
      };
    });
    frappe.confirm(
      __("Apply {0} User Permission value changes for {1}?", [changes.length, this.selected_user.full_name]),
      async () => {
        const response = await frappe.call({
          method: "marina_custom_apps.permission_manager.api.user_permissions.save_user_permission_values",
          args: { ...this.current_value_rule, user: this.selected_user.name, changes },
          freeze: true,
          freeze_message: __("Saving User Permissions..."),
        });
        const result = response.message;
        frappe.show_alert({
          message: __("Created {0}, updated {1}, deleted {2} User Permissions.", [
            result.created, result.updated, result.deleted,
          ]),
          indicator: "green",
        });
        await this.load_user_values();
      }
    );
  }

  discard_changes() {
    if (this.is_value_mode()) {
      this.discard_value_changes();
      return;
    }
    if (!this.pending.size) return;
    frappe.confirm(__("Discard all unsaved User Permission changes?"), async () => {
      this.users.forEach((user) => { user.assigned = this.initial_assigned.get(user.user); });
      this.default_touched = false;
      await this.with_suppressed_changes(() => this.default_field.set_value(this.loaded_default ? 1 : 0));
      this.pending.clear();
      this.users.forEach((user) => this.update_pending(user));
      this.update_save_button();
      this.render();
    });
  }

  discard_value_changes() {
    if (!this.value_pending.size) return;
    frappe.confirm(__("Discard all unsaved User Permission changes?"), () => {
      this.values.forEach((value) => {
        const initial = this.initial_values.get(value.for_value);
        value.assigned = Boolean(initial?.assigned);
        value.is_default = Boolean(initial?.is_default);
      });
      this.value_pending.clear();
      this.update_save_button();
      this.render();
    });
  }

  handle_permission_link(event) {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.button === 1) return;
    event.preventDefault();
    const name = $(event.currentTarget).attr("data-name");
    const open = () => frappe.set_route("Form", "User Permission", name);
    if (this.has_pending()) {
      frappe.confirm(__("Open this rule and leave the current unsaved changes?"), open);
    } else {
      open();
    }
  }

  handle_value_link(event) {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.button === 1) return;
    event.preventDefault();
    const value = $(event.currentTarget).attr("data-value");
    const open = () => frappe.set_route("Form", this.current_value_rule.allow, value);
    if (this.has_pending()) {
      frappe.confirm(__("Open this document and leave the current unsaved changes?"), open);
    } else {
      open();
    }
  }

  update_save_button() {
    const count = this.is_value_mode() ? this.value_pending.size : this.pending.size;
    const label = count ? __("Save Changes ({0})", [count]) : __("Save Changes");
    this.page.set_primary_action(label, () => this.save_changes(), "check");
    this.page.btn_primary.prop("disabled", !count);
  }

  show_empty(message) {
    this.body.html(`<div class="upm-empty text-muted">${this.escape(message)}</div>`);
  }

  escape(value) {
    return $("<div>").text(value == null ? "" : String(value)).html();
  }
}
