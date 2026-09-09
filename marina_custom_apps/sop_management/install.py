import json
from pathlib import Path

import frappe


ROLES = (
    ("SOP Manager", 1),
    ("SOP Editor", 1),
    ("SOP Viewer", 1),
)

DEFAULT_TYPES = (
    ("Policy", "POL", 10),
    ("Procedure", "PRO", 20),
    ("Work Instruction", "WI", 30),
    ("Guideline", "GUI", 40),
    ("Checklist", "CHK", 50),
)


def after_install():
    ensure_roles()
    ensure_default_types()
    sync_unified_workspace()


def after_migrate():
    ensure_roles()
    ensure_default_types()
    sync_unified_workspace()


def ensure_roles():
    if not frappe.db.exists("DocType", "Role"):
        return
    for role_name, desk_access in ROLES:
        if frappe.db.exists("Role", role_name):
            frappe.db.set_value(
                "Role", role_name, "desk_access", desk_access, update_modified=False
            )
            continue
        frappe.get_doc(
            {
                "doctype": "Role",
                "role_name": role_name,
                "desk_access": desk_access,
            }
        ).insert(ignore_permissions=True)


def ensure_default_types():
    if not frappe.db.exists("DocType", "SOP Type"):
        return
    for type_name, code, sort_order in DEFAULT_TYPES:
        if frappe.db.exists("SOP Type", type_name):
            continue
        frappe.get_doc(
            {
                "doctype": "SOP Type",
                "type_name": type_name,
                "code": code,
                "sort_order": sort_order,
                "is_active": 1,
            }
        ).insert(ignore_permissions=True)


def sync_unified_workspace():
    """Force the shipped umbrella workspace into the v15 database.

    Individual module workspaces are not deleted. This workspace provides the
    single Marina entry point requested by Management while existing links and
    permissions remain intact.
    """
    if not frappe.db.exists("DocType", "Workspace"):
        return

    workspace_file = (
        Path(__file__).resolve().parent
        / "workspace"
        / "marina_custom_apps"
        / "marina_custom_apps.json"
    )
    data = json.loads(workspace_file.read_text(encoding="utf-8"))

    # Remove links/shortcuts whose target is not installed. This keeps the
    # umbrella workspace safe across Demo/Live benches with slightly different
    # module rollout states.
    existing_links = []
    for row in data.get("links", []):
        if row.get("type") == "Card Break":
            existing_links.append(row)
            continue
        link_type = row.get("link_type")
        target = row.get("link_to")
        exists = True
        if link_type == "DocType":
            exists = bool(frappe.db.exists("DocType", target))
        elif link_type == "Page":
            exists = bool(frappe.db.exists("Page", target))
        elif link_type == "Report":
            exists = bool(frappe.db.exists("Report", target))
        if exists:
            existing_links.append(row)
    data["links"] = existing_links

    existing_shortcuts = []
    for row in data.get("shortcuts", []):
        target = row.get("link_to")
        row_type = row.get("type")
        exists = True
        if row_type == "DocType":
            exists = bool(frappe.db.exists("DocType", target))
        elif row_type == "Page":
            exists = bool(frappe.db.exists("Page", target))
        elif row_type == "Report":
            exists = bool(frappe.db.exists("Report", target))
        if exists:
            existing_shortcuts.append(row)
    data["shortcuts"] = existing_shortcuts

    # Content references shortcuts by label. Strip shortcut blocks which are
    # not installed so the workspace does not show broken tiles.
    installed_shortcut_labels = {row.get("label") for row in existing_shortcuts}
    content = json.loads(data.get("content") or "[]")
    content = [
        block
        for block in content
        if block.get("type") != "shortcut"
        or block.get("data", {}).get("shortcut_name") in installed_shortcut_labels
    ]
    data["content"] = json.dumps(content, separators=(",", ":"))

    child_tables = (
        "links",
        "shortcuts",
        "number_cards",
        "charts",
        "custom_blocks",
        "quick_lists",
        "roles",
    )

    name = data["name"]
    if frappe.db.exists("Workspace", name):
        doc = frappe.get_doc("Workspace", name)
        for fieldname in (
            "label", "title", "module", "icon", "public", "is_hidden",
            "hide_custom", "content", "parent_page", "sequence_id",
        ):
            if fieldname in data:
                doc.set(fieldname, data.get(fieldname))
        for table_field in child_tables:
            doc.set(table_field, [])
            for row in data.get(table_field, []):
                doc.append(table_field, row)
        if doc.meta.has_field("standard"):
            doc.standard = 1
        doc.save(ignore_permissions=True)
    else:
        doc = frappe.get_doc(data)
        if doc.meta.has_field("standard"):
            doc.standard = 1
        doc.insert(ignore_permissions=True)

    if frappe.get_meta("Workspace").has_field("standard"):
        frappe.db.set_value(
            "Workspace", name, "standard", 1, update_modified=False
        )

    frappe.clear_cache(doctype="Workspace")
