/* Marina Design Role Hierarchy: read-only view over Reports To Role.
   Role edits always use the existing permission-checked DocType form. */
frappe.pages["design-role-hierarchy"].on_page_load = function(wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper, title: __("Role Hierarchy"), single_column: true
    });
    const root = $('<div class="mdm-role-tree p-3"></div>').appendTo(page.main);
    const controls = $('<div class="d-flex flex-wrap align-items-center mb-3" style="gap:10px;"></div>')
        .appendTo(root);
    const search = $('<input type="search" class="form-control" style="max-width:330px;">')
        .attr("placeholder", __("Search roles or departments"))
        .attr("aria-label", __("Search roles or departments"))
        .appendTo(controls);
    const disabledLabel = $('<label class="mb-0 text-muted"></label>').appendTo(controls);
    const includeDisabled = $('<input type="checkbox" class="mr-1">').appendTo(disabledLabel);
    $('<span></span>').text(__("Show disabled roles")).appendTo(disabledLabel);
    const expand = $('<button type="button" class="btn btn-default btn-sm"></button>')
        .text(__("Expand All")).appendTo(controls);
    const collapse = $('<button type="button" class="btn btn-default btn-sm"></button>')
        .text(__("Collapse All")).appendTo(controls);
    const newRole = $('<button type="button" class="btn btn-primary btn-sm"></button>')
        .text(__("Add Role")).appendTo(controls).hide();
    const notice = $('<div class="text-muted mb-3"></div>')
        .text(__("Role reporting is configurable. Visibility and approval permissions are managed separately."))
        .appendTo(root);
    const status = $('<div class="text-muted small mb-2" role="status"></div>').appendTo(root);
    const tree = $('<div class="mdm-role-tree-rows" role="tree"></div>').appendTo(root);
    let roles = [];
    let canManage = false;
    let collapsed = new Set();

    function openRole(name) {
        frappe.set_route("Form", "Design Module Role", name);
    }

    function createChild(managerName) {
        if (!canManage) return;
        frappe.new_doc("Design Module Role", {
            reports_to_role: managerName || "Administrator",
            role_type: "Individual Contributor",
            scope: "Assigned",
            responsibility_group: "Other",
            frappe_role: "Marina Design Participant"
        });
    }

    function appendRole(node, level, children, included, visited, query) {
        if (visited.has(node.name) || !included.has(node.name)) return;
        visited.add(node.name);

        const availableChildren = (children.get(node.name) || [])
            .filter(child => included.has(child.name));
        const expanded = query.length > 0 || !collapsed.has(node.name);
        const row = $('<div class="d-flex align-items-center rounded mb-1 py-2 pr-2"></div>')
            .attr("role", "treeitem")
            .attr("aria-level", level + 1)
            .attr("aria-expanded", availableChildren.length ? String(expanded) : null)
            .css({
                "padding-left": Math.min(level, 16) * 20 + 8 + "px",
                "background-color": level === 0 ? "var(--subtle-accent, #f5f5f5)" : "transparent",
                "gap": "8px"
            }).appendTo(tree);

        const toggle = $('<button type="button" class="btn btn-default btn-xs"></button>')
            .attr("aria-label", __("Toggle subordinate roles"))
            .text(availableChildren.length ? (expanded ? "▾" : "▸") : "·")
            .prop("disabled", !availableChildren.length || Boolean(query))
            .appendTo(row);
        if (availableChildren.length) {
            toggle.on("click", () => {
                if (collapsed.has(node.name)) collapsed.delete(node.name);
                else collapsed.add(node.name);
                render();
            });
        }

        const label = $('<span class="font-weight-bold"></span>')
            .text(node.role_name || node.name).appendTo(row);
        if (!node.enabled) {
            $('<span class="text-muted small"></span>')
                .text(__("(Disabled)")).appendTo(row);
        }
        $('<span class="text-muted small"></span>')
            .text(node.role_type === "Manager" ? __("Manager") : __("Individual Contributor"))
            .appendTo(row);
        $('<span class="text-muted small d-none d-md-inline"></span>')
            .text(node.responsibility_group || "").appendTo(row);

        $('<button type="button" class="btn btn-link btn-xs ml-auto"></button>')
            .text(__("Open Role"))
            .on("click", () => openRole(node.name))
            .appendTo(row);

        if (canManage && node.enabled && node.role_type === "Manager") {
            $('<button type="button" class="btn btn-default btn-xs"></button>')
                .text(__("Add Subordinate"))
                .on("click", () => createChild(node.name))
                .appendTo(row);
        }
        if (expanded) {
            availableChildren.forEach(child =>
                appendRole(child, level + 1, children, included, visited, query));
        }
    }

    function render() {
        tree.empty();
        const query = search.val().trim().toLocaleLowerCase();
        const displayed = roles.filter(r => includeDisabled.prop("checked") || r.enabled);
        const byName = new Map(displayed.map(r => [r.name, r]));
        const children = new Map(displayed.map(r => [r.name, []]));
        const roots = [];
        displayed.forEach(r => {
            const parent = byName.get(r.reports_to_role);
            if (parent && r.reports_to_role !== r.name) {
                children.get(parent.name).push(r);
            } else if (r.name === "Administrator" && !r.reports_to_role) {
                roots.push(r);
            }
            // A missing/self-referential parent is handled by the Unlinked
            // section instead of silently becoming another organization root.
        });
        const sorter = (a, b) => (a.role_name || a.name)
            .localeCompare(b.role_name || b.name);
        roots.sort(sorter);
        children.forEach(rows => rows.sort(sorter));

        const included = new Set();
        if (query) {
            displayed.forEach(r => {
                const parts = [r.role_name, r.name, r.role_type, r.responsibility_group];
                if (!parts.some(value => String(value || "").toLocaleLowerCase().includes(query))) {
                    return;
                }
                // Search exposes the path to a matching role without a server
                // request and cannot enter an infinite loop in legacy bad data.
                let current = r;
                const path = new Set();
                while (current && !path.has(current.name)) {
                    path.add(current.name);
                    included.add(current.name);
                    current = byName.get(current.reports_to_role);
                }
            });
        } else {
            displayed.forEach(r => included.add(r.name));
        }

        // Reachability ignores collapsed state. Collapsed children are still
        // connected; they must NOT show again in "Other / Unlinked Roles".
        const reachable = new Set();
        function markReachable(node) {
            if (reachable.has(node.name) || !included.has(node.name)) return;
            reachable.add(node.name);
            (children.get(node.name) || []).forEach(markReachable);
        }
        roots.forEach(markReachable);

        const visited = new Set();
        roots.forEach(r => appendRole(r, 0, children, included, visited, query));

        // Only genuine cyclic/legacy disconnected components appear here.
        const unresolved = displayed.filter(r =>
            included.has(r.name) && !reachable.has(r.name));
        if (unresolved.length) {
            $('<div class="text-muted font-weight-bold mt-3 mb-2"></div>')
                .text(__("Other / Unlinked Roles")).appendTo(tree);
            unresolved.sort(sorter).forEach(r =>
                appendRole(r, 0, children, included, visited, query));
        }
        status.text(__("{0} roles shown", [visited.size]));
        if (!visited.size) {
            $('<div class="alert alert-info"></div>')
                .text(__("No matching roles.")).appendTo(tree);
        }
    }

    async function reload() {
        status.text(__("Loading roles…"));
        try {
            const {message} = await frappe.call({
                method: "marina_custom_apps.design_management.api.role_hierarchy.get_role_hierarchy"
            });
            roles = message?.roles || [];
            canManage = Boolean(message?.can_manage);
            newRole.toggle(canManage);
            render();
        } catch (error) {
            roles = [];
            tree.empty();
            status.text(__("Unable to load the role hierarchy."));
            newRole.hide();
            // Authorization failures are shown by Frappe's request UI.
        }
    }

    search.on("input", render);
    includeDisabled.on("change", render);
    expand.on("click", () => { collapsed.clear(); render(); });
    collapse.on("click", () => {
        collapsed = new Set(roles.filter(r => r.role_type === "Manager").map(r => r.name));
        render();
    });
    newRole.on("click", () => createChild());
    page.add_inner_button(__("Refresh"), reload);
    wrapper.mdm_role_hierarchy_reload = reload;
};

frappe.pages["design-role-hierarchy"].on_page_show = function(wrapper) {
    if (wrapper.mdm_role_hierarchy_reload) wrapper.mdm_role_hierarchy_reload();
};
