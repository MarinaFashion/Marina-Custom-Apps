"""Create exactly eleven approved Module Roles on a clean install.

Users are not assigned automatically. Administrators explicitly configure
active User→Module Role assignments in Design Management Settings.
"""
import frappe
from marina_custom_apps.design_management.security.organization import REPORTS_TO, HEADS, DEFAULT_GROUPS

ROLE_FRAPPE = {name: "Marina Design Participant" for name in REPORTS_TO}
DOCUMENTS = {
    "Mood Board":"rcw", "Design Code":"rcw", "Design Document":"rcw",
    "Design Milestone Execution":"r", "Design Milestone Plan Entry":"r",
    "Design Milestone Custody Event":"r", "Production Colorway":"rw",
    "Design Item Creation":"r", "Design Milestone Type":"r",
    "Marina Pantone":"r", "Marina Fashion Category":"r",
    "Design Document Type":"r",
    "Design Cost Breakdown":"r",
}


def _actions(name):
    actions=["Advance Milestone Step"]
    if name in {"Administrator", "Merchandiser", "Head Of Merchandisers"}:
        actions.append("Set Initial Fabric Approval")
    if name in {"Administrator", "Designer"}:
        actions.append("Change Fabric Approval")
    if name in HEADS:
        actions.extend(["Assign Team Tasks", "Reassign Team Tasks"])
    if name in {"Administrator", "China Office Manager",
                "Head Of Merchandisers", "Merchandiser"}:
        actions.append("Assign Milestones")
    if name in {"Administrator", "QC Manager", "Technical Fitting Manager"}:
        actions.append("Publish Document")
    if name in {"Administrator", "Merchandiser"}:
        actions.append("Create ERPNext Items")
    if name in {"Administrator", "Buying Manager"}:
        actions.append("Approve Design Cost Breakdown")
    if name=="Administrator":
        actions.extend(["Delete Design Code", "Return to Milestone",
                        "Remove Published Assignment", "Manage Role Permissions"])
    return actions


def sync_module_roles():
    if not frappe.db.exists("DocType", "Design Module Role"):
        return
    for name, parent in REPORTS_TO.items():
        if frappe.db.exists("Design Module Role", name):
            # Do not overwrite the user's security settings on later migrates.
            continue
        permissions=dict(DOCUMENTS)
        if name in ("Merchandiser", "Head Of Merchandisers", "Administrator"):
            permissions["Design Cost Breakdown"] = "rcw"
        elif name not in ("Buying Manager",):
            permissions.pop("Design Cost Breakdown", None)
        if name=="Administrator":
            permissions.update({
                "Design Module Role":"rcwd",
                "Design Management Settings":"rcwd",
            })
        elif name not in HEADS and name not in {"Designer","Merchandiser",
                                                  "Technical Fitting Officer"}:
            permissions["Design Code"]="r"
        doc=frappe.get_doc({
            "doctype":"Design Module Role",
            "role_name":name, "frappe_role":"Marina Design Participant",
            "scope":"All" if name in HEADS else "Assigned",
            "reports_to_role":parent,
            "role_type":"Manager" if name in HEADS else "Individual Contributor",
            "responsibility_group":DEFAULT_GROUPS[name],
            "enabled":1,
            "description":"Clean Marina Design Module Role",
        })
        for doctype, flags in permissions.items():
            if frappe.db.exists("DocType",doctype):
                doc.append("doctype_permissions",{
                    "resource_doctype":doctype,
                    "read":int("r" in flags),
                    "create":int("c" in flags),
                    "write":int("w" in flags),
                    "delete":int("d" in flags),
                })
        for action in _actions(name):
            doc.append("action_permissions",{"action_key":action,"allowed":1})
        frappe.flags.marina_seeding_roles=True
        try:
            doc.insert(ignore_permissions=True)
        finally:
            frappe.flags.marina_seeding_roles=False


def sync_cost_breakdown_permissions():
    """Add ONLY missing Cost Breakdown child rows during install/migrate.

    Older Design Module Role records may contain legacy links to retired
    DocTypes. Saving the entire parent would revalidate those unrelated rows
    and fail migration. Inserting one explicitly validated child at a time
    avoids touching old permissions, assignments, descriptions, or reporting.

    No manual transaction commit: bench migrate owns rollback/commit.
    """
    doctype = "Design Cost Breakdown"
    action = "Approve Design Cost Breakdown"
    if not frappe.db.exists("DocType", doctype):
        return

    defaults = {
        "Merchandiser": (1, 1, 1),
        "Head Of Merchandisers": (1, 1, 1),
        "Buying Manager": (1, 0, 0),
        "Administrator": (1, 1, 1),
    }

    def append_if_missing(child_type, parent, parentfield, identity, data):
        existing = frappe.db.exists(child_type, {
            "parenttype": "Design Module Role",
            "parent": parent,
            "parentfield": parentfield,
            **identity,
        })
        if existing:
            return False
        # Child table order is stable; calculating it from this one table
        # avoids fetching or saving the full (possibly legacy) parent.
        max_idx = frappe.db.sql(
            "SELECT COALESCE(MAX(idx), 0) FROM `tab" + child_type +
            "` WHERE parent=%s AND parenttype=%s AND parentfield=%s",
            (parent, "Design Module Role", parentfield),
        )[0][0]
        child = frappe.get_doc({
            "doctype": child_type,
            "parent": parent,
            "parenttype": "Design Module Role",
            "parentfield": parentfield,
            "idx": int(max_idx or 0) + 1,
            **data,
        })
        # Frappe v15 db_insert sets a proper child name and writes only this
        # newly created record. It deliberately does not validate/save all
        # existing children of the parent. All values above are fixed,
        # server-validated migration constants, never user input.
        child.db_insert()
        return True

    added = False
    for role, (read, create, write) in defaults.items():
        if not frappe.db.exists("Design Module Role", role):
            continue
        added |= append_if_missing(
            "Design Module DocType Permission", role, "doctype_permissions",
            {"resource_doctype": doctype},
            {"resource_doctype": doctype, "read": read,
             "create": create, "write": write, "delete": 0},
        )
        if role in ("Administrator", "Buying Manager"):
            added |= append_if_missing(
                "Design Module Action Permission", role, "action_permissions",
                {"action_key": action},
                {"action_key": action, "allowed": 1},
            )
        frappe.clear_document_cache("Design Module Role", role)

    if added:
        from marina_custom_apps.design_management.security.organization import clear_role_cache
        clear_role_cache()
