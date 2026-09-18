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
    this.workflow = "create";
    this.review_rows = [];
    this.review_initial = new Map();
    this.review_pending = new Set();
    this.review_deleted = new Set();
    this.review_loaded = false;
    this.review_has_more = false;
    this.review_next_start = 0;
    this.review_loaded_filters = null;

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
      change: () => this.is_review_mode()
        ? this.handle_review_filter_change()
        : this.handle_user_selection_change(),
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
      change: () => this.is_review_mode() ? this.handle_review_filter_change() : this.render(),
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
      change: () => this.is_review_mode() ? this.handle_review_filter_change() : this.render(),
    });

    this.page.set_primary_action(__("Save Changes"), () => this.save_changes(), "check");
    this.page.add_inner_button(__("Discard Changes"), () => this.discard_changes());
    this.page.add_inner_button(
      __("Load Current Permissions"),
      () => this.open_review_mode()
    );
    this.page.add_inner_button(
      __("Create / Manage Permissions"),
      () => this.open_create_mode()
    );
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
    this.body.on("change", ".upm-review-delete", (event) => this.handle_review_delete(event));
    this.body.on("change", ".upm-review-delete-all", (event) => this.handle_review_delete_all(event));
    this.body.on("change", ".upm-review-apply-all", (event) => this.handle_review_apply_all(event));
    this.body.on("change", ".upm-review-default", (event) => this.handle_review_default(event));
    this.body.on("click", ".upm-review-applicable", (event) => this.handle_review_applicable(event));
    this.body.on("click", ".upm-review-load-more", () => this.load_current_permissions(true));
    this.body.on("click", ".upm-review-link", (event) => this.handle_review_link(event));
  }

  is_review_mode() {
    return this.workflow === "review";
  }

  is_value_mode() {
    return this.mode_field.get_value() !== "Users for Permission";
  }

  has_pending() {
    return this.value_pending.size > 0 || this.pending.size > 0
      || this.review_pending.size > 0 || this.review_deleted.size > 0;
  }

  apply_all_enabled() {
    const value = this.apply_all_field.get_value();
    return value === true || value === 1 || value === "1" || value === "true";
  }

  open_review_mode() {
    if (this.is_review_mode()) {
      if (this.has_pending()) {
        frappe.confirm(
          __("Discard the unsaved review changes and reload current permissions?"),
          () => this.load_current_permissions()
        );
      } else {
        this.load_current_permissions();
      }
      return;
    }
    const open = async () => {
      this.workflow = "review";
      this.clear_loaded_rule();
      this.clear_loaded_values();
      this.configure_mode();
      await this.with_suppressed_changes(() => this.user_status_field.set_value("All"));
      await this.load_current_permissions();
    };
    if (this.has_pending()) {
      frappe.confirm(__("Discard the unsaved User Permission changes?"), open);
    } else {
      open();
    }
  }

  open_create_mode() {
    const open = () => {
      this.workflow = "create";
      this.clear_review();
      this.configure_mode();
      this.show_mode_empty();
      this.update_save_button();
    };
    if (this.has_pending()) {
      frappe.confirm(__("Discard the unsaved User Permission changes?"), open);
    } else {
      open();
    }
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
    if (this.is_review_mode()) {
      this.mode_field.toggle(false);
      this.user_field.toggle(true);
      this.user_field.df.reqd = 0;
      this.user_field.refresh();
      this.allow_field.df.reqd = 0;
      this.allow_field.refresh();
      this.value_field.toggle(false);
      this.apply_all_field.toggle(false);
      this.default_field.toggle(false);
      this.applicable_field.toggle(true);
      this.applicable_field.df.reqd = 0;
      this.user_status_field.toggle(true);
      this.status_field.df.options = [
        "", "Modified", "Marked for Deletion", "Default", "Apply To All", "Scoped",
      ];
      this.status_field.set_value("");
      this.status_field.refresh();
      this.search_field.df.label = __("Search Permissions");
      this.search_field.refresh();
      this.search_field.$input?.attr("placeholder", __("Search Permissions"));
      this.update_scope_controls();
      return;
    }
    const value_mode = this.is_value_mode();
    this.mode_field.toggle(true);
    this.allow_field.df.reqd = 1;
    this.allow_field.refresh();
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
    this.search_field.$input?.attr("placeholder", value_mode ? __("Search Value") : __("Search User"));
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
    if (this.is_review_mode()) {
      this.handle_review_filter_change();
      return;
    }
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
    if (this.is_review_mode()) {
      this.handle_review_filter_change();
      return;
    }
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
    if (this.is_review_mode()) {
      this.apply_all_field.toggle(false);
      this.default_field.toggle(false);
      this.applicable_field.toggle(true);
      this.applicable_field.df.reqd = 0;
      this.applicable_field.refresh();
      return;
    }
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

  handle_review_filter_change() {
    if (!this.review_loaded || this.suppress_changes) return;
    const reload = () => this.load_current_permissions();
    if (this.has_pending()) {
      frappe.confirm(
        __("Discard unsaved review changes and apply the new filters?"),
        reload,
        () => this.restore_review_filter_controls()
      );
    } else {
      reload();
    }
  }

  clear_review() {
    this.review_rows = [];
    this.review_initial.clear();
    this.review_pending.clear();
    this.review_deleted.clear();
    this.review_loaded = false;
    this.review_has_more = false;
    this.review_next_start = 0;
    this.review_loaded_filters = null;
  }

  review_filters() {
    return {
      user: this.user_field.get_value() || "",
      user_status: this.user_status_field.get_value() || "All",
      allow: this.allow_field.get_value() || "",
      applicable_for: this.applicable_field.get_value() || "",
      search: this.search_field.get_value() || "",
    };
  }

  async load_current_permissions(append = false) {
    if (!this.is_review_mode()) return;
    if (append && this.has_pending()) {
      frappe.msgprint(__("Save or discard the current changes before loading more records."));
      return;
    }
    const filters = this.review_filters();
    const response = await frappe.call({
      method: "marina_custom_apps.permission_manager.api.user_permissions.get_current_user_permissions",
      args: {
        ...filters,
        start: append ? this.review_next_start : 0,
        page_length: 200,
      },
      freeze: true,
      freeze_message: __("Loading current User Permissions..."),
    });
    const result = response.message || {};
    if (!append) this.clear_review();
    const rows = result.rows || [];
    rows.forEach((row) => {
      row.enabled = Boolean(row.enabled);
      row.apply_to_all_doctypes = Boolean(row.apply_to_all_doctypes);
      row.is_default = Boolean(row.is_default);
      row.applicable_for = row.applicable_for || "";
      this.review_rows.push(row);
      this.review_initial.set(row.name, {
        apply_to_all_doctypes: row.apply_to_all_doctypes,
        applicable_for: row.applicable_for,
        is_default: row.is_default,
      });
    });
    this.review_loaded = true;
    this.review_has_more = Boolean(result.has_more);
    this.review_next_start = result.next_start || this.review_rows.length;
    this.review_loaded_filters = filters;
    this.update_save_button();
    this.render();
  }

  async restore_review_filter_controls() {
    if (!this.review_loaded_filters) return;
    const filters = this.review_loaded_filters;
    await this.with_suppressed_changes(async () => {
      await this.user_field.set_value(filters.user || "");
      await this.user_status_field.set_value(filters.user_status || "All");
      await this.allow_field.set_value(filters.allow || "");
      await this.applicable_field.set_value(filters.applicable_for || "");
      await this.search_field.set_value(filters.search || "");
    });
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
    if (this.is_review_mode()) {
      this.render_review_mode();
      return;
    }
    if (this.is_value_mode()) this.render_values_mode();
    else this.render_users_mode();
  }

  visible_review_rows() {
    const status = this.status_field.get_value();
    return this.review_rows.filter((row) => {
      if (status === "Modified" && !this.review_pending.has(row.name)) return false;
      if (status === "Marked for Deletion" && !this.review_deleted.has(row.name)) return false;
      if (status === "Default" && !row.is_default) return false;
      if (status === "Apply To All" && !row.apply_to_all_doctypes) return false;
      if (status === "Scoped" && row.apply_to_all_doctypes) return false;
      return true;
    });
  }

  render_review_mode() {
    if (!this.review_loaded) {
      this.show_empty(__("Use Load Current Permissions to review existing User Permission records."));
      return;
    }
    const visible = this.visible_review_rows();
    const inactive = this.review_rows.filter((row) => !row.enabled).length;
    const rows = visible.length
      ? visible.map((row) => this.render_review_row(row)).join("")
      : `<tr><td colspan="9" class="text-muted text-center p-4">${__("No permissions match the current filters.")}</td></tr>`;
    const more = this.review_has_more
      ? `<button class="btn btn-default btn-sm upm-review-load-more">${__("Load More")}</button>`
      : "";
    this.body.html(`
      <section class="upm-summary">
        <div><strong>${__("Current User Permissions")}</strong></div>
        <div class="upm-metrics">
          <span>${this.review_rows.length} ${__("loaded")}</span>
          <span>${inactive} ${__("belong to inactive users")}</span>
          <span>${this.review_pending.size} ${__("modified")}</span>
          <span>${this.review_deleted.size} ${__("marked for deletion")}</span>
          ${more}
        </div>
      </section>
      <div class="alert alert-info upm-help">
        ${__("This view loads existing records only. User, Allow, and Value stay unchanged; scope and Default can be edited, and selected records can be deleted.")}
      </div>
      <div class="upm-table-wrap upm-review-table-wrap">
        <table class="table table-bordered upm-table upm-review-table">
          <colgroup>
            <col style="width:18%"><col style="width:8%">
            <col style="width:13%"><col style="width:20%"><col style="width:8%">
            <col style="width:14%"><col style="width:7%"><col style="width:8%"><col style="width:4%">
          </colgroup>
          <thead><tr>
            <th>${__("User")}</th>
            <th>${__("Status")}</th>
            <th>${__("Allow")}</th>
            <th>${__("Value")}</th>
            <th>${__("Apply All")}</th>
            <th>${__("Applicable For")}</th>
            <th>${__("Default")}</th>
            <th>${__("Permission")}</th>
            <th class="upm-check-cell"><input type="checkbox" class="upm-review-delete-all" title="${__("Mark visible records for deletion")}"></th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `);
    const deleted = visible.filter((row) => this.review_deleted.has(row.name)).length;
    this.body.find(".upm-review-delete-all")
      .prop("checked", Boolean(visible.length && deleted === visible.length))
      .prop("indeterminate", deleted > 0 && deleted < visible.length);
  }

  render_review_row(row) {
    const modified = this.review_pending.has(row.name) || this.review_deleted.has(row.name);
    const deleting = this.review_deleted.has(row.name);
    const row_class = `${modified ? " upm-row-modified" : ""}${deleting ? " upm-row-deleted" : ""}`;
    const user_label = row.full_name === row.user
      ? this.escape(row.user)
      : `${this.escape(row.full_name)}<div class="text-muted">${this.escape(row.user)}</div>`;
    const user_link = `<a class="upm-review-link" href="/app/user/${encodeURIComponent(row.user)}" data-doctype="User" data-name="${this.escape(row.user)}">${user_label} ↗</a>`;
    const allow_link = `<a class="upm-review-link" href="/app/doctype/${frappe.router.slug(row.allow)}" data-doctype="DocType" data-name="${this.escape(row.allow)}">${this.escape(row.allow)} ↗</a>`;
    const value_link = row.missing
      ? `${this.escape(row.label)} <span class="indicator-pill orange">${__("Missing")}</span>`
      : `<a class="upm-review-link" href="/app/${frappe.router.slug(row.allow)}/${encodeURIComponent(row.for_value)}" data-doctype="${this.escape(row.allow)}" data-name="${this.escape(row.for_value)}">${this.escape(row.label)} ↗</a>`;
    const applicable = row.apply_to_all_doctypes
      ? `<span class="text-muted">${__("All document types")}</span>`
      : `<button class="btn btn-link btn-xs upm-review-applicable" data-name="${this.escape(row.name)}" ${deleting ? "disabled" : ""}>${this.escape(row.applicable_for || __("Select"))} ✎</button>`;
    const permission = `<a class="upm-permission-link" href="/app/user-permission/${encodeURIComponent(row.name)}" data-name="${this.escape(row.name)}">${this.escape(row.name)} ↗</a>`;
    return `
      <tr class="upm-review-row${row_class}" data-name="${this.escape(row.name)}">
        <td>${user_link}</td>
        <td><span class="indicator-pill ${row.enabled ? "green" : "gray"}">${row.enabled ? __("Active") : __("Inactive")}</span></td>
        <td>${allow_link}</td>
        <td>${value_link}</td>
        <td class="upm-check-cell"><input type="checkbox" class="upm-review-apply-all" data-name="${this.escape(row.name)}" ${row.apply_to_all_doctypes ? "checked" : ""} ${deleting ? "disabled" : ""}></td>
        <td>${applicable}</td>
        <td class="upm-check-cell"><input type="checkbox" class="upm-review-default" data-name="${this.escape(row.name)}" ${row.is_default ? "checked" : ""} ${deleting ? "disabled" : ""}></td>
        <td>${permission}</td>
        <td class="upm-check-cell"><input type="checkbox" class="upm-review-delete" data-name="${this.escape(row.name)}" ${deleting ? "checked" : ""}></td>
      </tr>`;
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
      : `<tr><td colspan="4" class="text-muted text-center p-4">${__("No values match the current filters.")}</td></tr>`;
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
          <colgroup><col style="width:44%"><col style="width:28%"><col style="width:12%"><col style="width:16%"></colgroup>
          <thead><tr>
            <th>${__("Value")}</th>
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

  review_row(name) {
    return this.review_rows.find((row) => row.name === name);
  }

  update_review_pending(row) {
    const initial = this.review_initial.get(row.name);
    const changed = initial && (
      row.apply_to_all_doctypes !== initial.apply_to_all_doctypes
      || row.applicable_for !== initial.applicable_for
      || row.is_default !== initial.is_default
    );
    if (changed) this.review_pending.add(row.name);
    else this.review_pending.delete(row.name);
  }

  handle_review_delete(event) {
    const input = $(event.currentTarget);
    const name = input.attr("data-name");
    if (input.is(":checked")) this.review_deleted.add(name);
    else this.review_deleted.delete(name);
    this.update_save_button();
    this.render();
  }

  handle_review_delete_all(event) {
    const deleting = $(event.currentTarget).is(":checked");
    this.visible_review_rows().forEach((row) => {
      if (deleting) this.review_deleted.add(row.name);
      else this.review_deleted.delete(row.name);
    });
    this.update_save_button();
    this.render();
  }

  handle_review_apply_all(event) {
    const input = $(event.currentTarget);
    const row = this.review_row(input.attr("data-name"));
    if (!row) return;
    row.apply_to_all_doctypes = input.is(":checked");
    if (row.apply_to_all_doctypes) row.applicable_for = "";
    this.update_review_pending(row);
    this.update_save_button();
    this.render();
  }

  handle_review_default(event) {
    const input = $(event.currentTarget);
    const row = this.review_row(input.attr("data-name"));
    if (!row) return;
    row.is_default = input.is(":checked");
    this.update_review_pending(row);
    this.update_save_button();
    this.render();
  }

  handle_review_applicable(event) {
    event.preventDefault();
    const row = this.review_row($(event.currentTarget).attr("data-name"));
    if (!row || row.apply_to_all_doctypes || this.review_deleted.has(row.name)) return;
    frappe.prompt(
      [{
        fieldname: "applicable_for",
        label: __("Applicable For"),
        fieldtype: "Link",
        options: "DocType",
        reqd: 1,
        default: row.applicable_for,
        get_query: () => ({
          query: "frappe.core.doctype.user_permission.user_permission.get_applicable_for_doctype_list",
          doctype: row.allow,
        }),
      }],
      (values) => {
        row.applicable_for = values.applicable_for;
        this.update_review_pending(row);
        this.update_save_button();
        this.render();
      },
      __("Change Permission Scope"),
      __("Apply")
    );
  }

  handle_review_link(event) {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.button === 1) return;
    event.preventDefault();
    const link = $(event.currentTarget);
    const open = () => frappe.set_route("Form", link.attr("data-doctype"), link.attr("data-name"));
    if (this.has_pending()) {
      frappe.confirm(__("Open this record and leave the current unsaved changes?"), open);
    } else {
      open();
    }
  }

  save_review_changes() {
    const names = new Set([...this.review_pending, ...this.review_deleted]);
    if (!names.size) {
      frappe.show_alert({ message: __("There are no changes to save."), indicator: "blue" });
      return;
    }
    const changes = [...names].map((name) => {
      const row = this.review_row(name);
      return {
        name,
        deleted: this.review_deleted.has(name) ? 1 : 0,
        apply_to_all_doctypes: row.apply_to_all_doctypes ? 1 : 0,
        applicable_for: row.applicable_for || "",
        is_default: row.is_default ? 1 : 0,
      };
    });
    frappe.confirm(
      __("Save {0} existing User Permission changes? Records marked for deletion will be permanently removed.", [changes.length]),
      async () => {
        const response = await frappe.call({
          method: "marina_custom_apps.permission_manager.api.user_permissions.save_current_user_permissions",
          args: { changes },
          freeze: true,
          freeze_message: __("Saving current User Permissions..."),
        });
        const result = response.message || {};
        frappe.show_alert({
          message: __("Updated {0} and deleted {1} User Permissions.", [result.updated, result.deleted]),
          indicator: "green",
        });
        await this.load_current_permissions();
      }
    );
  }

  save_changes() {
    if (this.is_review_mode()) {
      this.save_review_changes();
      return;
    }
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
    if (this.is_review_mode()) {
      if (!this.review_pending.size && !this.review_deleted.size) return;
      frappe.confirm(__("Discard all unsaved User Permission changes?"), () => {
        this.review_rows.forEach((row) => {
          const initial = this.review_initial.get(row.name);
          row.apply_to_all_doctypes = initial.apply_to_all_doctypes;
          row.applicable_for = initial.applicable_for;
          row.is_default = initial.is_default;
        });
        this.review_pending.clear();
        this.review_deleted.clear();
        this.update_save_button();
        this.render();
      });
      return;
    }
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
    const count = this.is_review_mode()
      ? new Set([...this.review_pending, ...this.review_deleted]).size
      : (this.is_value_mode() ? this.value_pending.size : this.pending.size);
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
