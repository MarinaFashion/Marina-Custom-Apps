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
    ensure_document_numbers()
    ensure_controlled_print_format()
    ensure_umbrella_module_def()
    sync_unified_workspace()
    sync_module_workspace_hierarchy()


def after_migrate():
    ensure_roles()
    ensure_default_types()
    ensure_document_numbers()
    ensure_controlled_print_format()
    ensure_umbrella_module_def()
    sync_unified_workspace()
    sync_module_workspace_hierarchy()


def ensure_umbrella_module_def():
    """Ensure the umbrella Workspace module exists on already-installed sites.

    Adding a new entry to modules.txt gives Frappe the module package to sync,
    but existing sites do not necessarily get a matching Module Def row before
    after_migrate hooks run. Workspace.module is a Link to Module Def, so the
    row must exist before saving the Marina Custom Apps workspace.
    """
    if not frappe.db.exists("DocType", "Module Def"):
        return

    module_name = "Marina Custom Apps"
    app_name = "marina_custom_apps"

    if frappe.db.exists("Module Def", module_name):
        frappe.db.set_value(
            "Module Def",
            module_name,
            {
                "module_name": module_name,
                "app_name": app_name,
                "custom": 0,
            },
            update_modified=False,
        )
        return

    frappe.get_doc(
        {
            "doctype": "Module Def",
            "module_name": module_name,
            "app_name": app_name,
            "custom": 0,
        }
    ).insert(ignore_permissions=True)


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


def ensure_document_numbers():
    if not frappe.db.exists("DocType", "SOP Document"):
        return
    rows = frappe.get_all("SOP Document", filters={"document_no": ["is", "not set"]}, pluck="name", limit_page_length=0)
    for name in rows:
        frappe.db.set_value("SOP Document", name, "document_no", name, update_modified=False)


CONTROLLED_PRINT_FORMAT = "Marina SOP Controlled Document"


def ensure_controlled_print_format():
    """Create/update the Marina-controlled SOP/JD presentation layer.

    Content remains stored as rich HTML in SOP Section rows. The print format
    supplies the branded, consistent document shell for preview/print/PDF.
    """
    if not frappe.db.exists("DocType", "Print Format"):
        return

    html = r"""
{% set parent = frappe.get_doc("SOP Document", doc.sop_document) %}
{% set lang = doc.language or parent.language or "English" %}
{% set status_ar = {
    "Draft": "مسودة",
    "Pending Approval": "بانتظار الاعتماد",
    "Approved": "معتمد",
    "Published": "منشور",
    "Archived": "مؤرشف",
    "Cancelled": "ملغى"
} %}
{% set versions = frappe.get_all(
    "SOP Version",
    filters={"sop_document": doc.sop_document},
    fields=["version_no", "status", "effective_from", "approved_by", "approved_on", "published_by", "published_on", "change_summary"],
    order_by="version_no desc"
) %}

<style>
.sop-controlled {
    font-family: Arial, "Helvetica Neue", sans-serif;
    color: #2D2926;
    font-size: 10.5pt;
    line-height: 1.55;
}
.sop-controlled .brand-bar {
    border-top: 7px solid #551C25;
    border-bottom: 2px solid #C0A392;
    padding: 14px 0 12px;
    margin-bottom: 14px;
}
.sop-controlled .brand {
    font-size: 19pt;
    font-weight: 700;
    letter-spacing: .6px;
    color: #551C25;
}
.sop-controlled .doc-kind {
    font-size: 9pt;
    color: #6B5B57;
    text-transform: uppercase;
    letter-spacing: 1px;
}
.sop-controlled .title-en,
.sop-controlled .title-ar {
    font-size: 17pt;
    font-weight: 700;
    color: #2D2926;
    margin: 10px 0 3px;
}
.sop-controlled .title-ar {
    direction: rtl;
    text-align: right;
}
.sop-controlled .meta {
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0 22px;
    table-layout: fixed;
}
.sop-controlled .meta th,
.sop-controlled .meta td {
    border: 1px solid #E4D5C4;
    padding: 7px 8px;
    vertical-align: top;
}
.sop-controlled .meta th {
    background: #F2EBE7;
    color: #551C25;
    font-weight: 700;
    width: 16%;
}
.sop-controlled .meta.rtl,
.sop-controlled .revision.rtl {
    direction: rtl;
    text-align: right;
}
.sop-controlled .section {
    margin: 0 0 22px;
    page-break-inside: avoid;
}
.sop-controlled .section-heading {
    background: #551C25;
    color: #fff;
    padding: 7px 10px;
    font-size: 12pt;
    font-weight: 700;
    border-left: 5px solid #C0A392;
    margin-bottom: 9px;
}
.sop-controlled .section-heading.rtl {
    direction: rtl;
    text-align: right;
    border-left: 0;
    border-right: 5px solid #C0A392;
}
.sop-controlled .sop-body {
    padding: 0 4px;
}
.sop-controlled .sop-body.rtl {
    direction: rtl;
    text-align: right;
}
.sop-controlled .sop-body table,
.sop-controlled .sop-custom-content table {
    width: 100% !important;
    border-collapse: collapse !important;
    margin: 10px 0 15px !important;
}
.sop-controlled .sop-body table th,
.sop-controlled .sop-body table td,
.sop-controlled .sop-custom-content table th,
.sop-controlled .sop-custom-content table td {
    border: 1px solid #C0A392 !important;
    padding: 7px 8px !important;
    vertical-align: top !important;
}
.sop-controlled .sop-body table th,
.sop-controlled .sop-custom-content table th {
    background: #E4D5C4 !important;
    color: #551C25 !important;
    font-weight: 700 !important;
}
.sop-controlled .sop-body h1,
.sop-controlled .sop-body h2,
.sop-controlled .sop-body h3,
.sop-controlled .sop-body h4 {
    color: #551C25;
    margin-top: 14px;
}
.sop-controlled .sop-body ul,
.sop-controlled .sop-body ol {
    padding-left: 22px;
}
.sop-controlled .revision-title {
    margin-top: 26px;
    font-size: 12pt;
    font-weight: 700;
    color: #551C25;
    border-bottom: 2px solid #C0A392;
    padding-bottom: 4px;
}
.sop-controlled .revision {
    width: 100%;
    border-collapse: collapse;
    margin-top: 8px;
    font-size: 9pt;
}
.sop-controlled .revision th,
.sop-controlled .revision td {
    border: 1px solid #E4D5C4;
    padding: 6px 7px;
}
.sop-controlled .revision th {
    background: #F2EBE7;
    color: #551C25;
}
.sop-controlled .control-footer {
    margin-top: 25px;
    padding-top: 8px;
    border-top: 1px solid #C0A392;
    font-size: 8.5pt;
    color: #6B5B57;
    display: flex;
    justify-content: space-between;
}
@media print {
    .sop-controlled .section { page-break-inside: avoid; }
    .sop-controlled .revision { page-break-inside: avoid; }
}
</style>

<div class="sop-controlled">
    <div class="brand-bar">
        {% if lang in ("English", "Bilingual") %}
            <div class="brand">Marina Fashion - SOP System</div>
            <div class="doc-kind">{{ parent.sop_type or "Controlled Document" }}</div>
        {% endif %}
        {% if lang in ("Arabic", "Bilingual") %}
            <div class="brand title-ar" style="font-size:15pt">مارينا فاشون - دليل الإجراءات القياسية التشغيلية</div>
        {% endif %}
        {% if lang in ("English", "Bilingual") and parent.title_en %}
            <div class="title-en">{{ parent.title_en }}</div>
        {% endif %}
        {% if lang in ("Arabic", "Bilingual") and parent.title_ar %}
            <div class="title-ar">{{ parent.title_ar }}</div>
        {% endif %}
    </div>

    <table class="meta{% if lang == "Arabic" %} rtl{% endif %}">
        <tr>
            <th>{% if lang == "Arabic" %}رقم الوثيقة{% elif lang == "Bilingual" %}Document No. / رقم الوثيقة{% else %}Document No.{% endif %}</th><td>{{ parent.document_no or parent.name }}</td>
            <th>{% if lang == "Arabic" %}الإصدار{% elif lang == "Bilingual" %}Version / الإصدار{% else %}Version{% endif %}</th><td>{{ doc.version_no }}</td>
        </tr>
        <tr>
            <th>{% if lang == "Arabic" %}الإدارة{% elif lang == "Bilingual" %}Department / الإدارة{% else %}Department{% endif %}</th><td>{{ parent.department or "" }}</td>
            <th>{% if lang == "Arabic" %}الحالة{% elif lang == "Bilingual" %}Status / الحالة{% else %}Status{% endif %}</th><td>{% if lang == "Arabic" %}{{ status_ar.get(doc.status, doc.status) }}{% else %}{{ doc.status }}{% endif %}</td>
        </tr>
        <tr>
            <th>{% if lang == "Arabic" %}تاريخ السريان{% elif lang == "Bilingual" %}Effective Date / تاريخ السريان{% else %}Effective Date{% endif %}</th><td>{{ doc.effective_from or "" }}</td>
            <th>{% if lang == "Arabic" %}اللغة{% elif lang == "Bilingual" %}Language / اللغة{% else %}Language{% endif %}</th><td>{% if lang == "Arabic" %}العربية{% elif lang == "Bilingual" %}Bilingual / ثنائي اللغة{% else %}English{% endif %}</td>
        </tr>
        <tr>
            <th>{% if lang == "Arabic" %}مالك العملية{% elif lang == "Bilingual" %}Process Owner / مالك العملية{% else %}Process Owner{% endif %}</th><td>{{ parent.process_owner or "" }}</td>
            <th>{% if lang == "Arabic" %}اعتمد بواسطة{% elif lang == "Bilingual" %}Approved By / اعتمد بواسطة{% else %}Approved By{% endif %}</th><td>{{ doc.approved_by or "" }}</td>
        </tr>
    </table>

    {% if lang in ("English", "Bilingual") and parent.summary %}
        <div class="section">
            <div class="section-heading">Document Summary</div>
            <div class="sop-body">{{ parent.summary }}</div>
        </div>
    {% endif %}
    {% if lang in ("Arabic", "Bilingual") and parent.summary_ar %}
        <div class="section">
            <div class="section-heading rtl">&#1605;&#1604;&#1582;&#1589; &#1575;&#1604;&#1608;&#1579;&#1610;&#1602;&#1577;</div>
            <div class="sop-body rtl">{{ parent.summary_ar }}</div>
        </div>
    {% endif %}

    {% if doc.content_mode == "Advanced HTML" %}
        <div class="sop-custom-content">{{ (doc.html_content or "") | safe }}</div>
    {% else %}
        {% for row in doc.sections %}
            {% if lang in ("English", "Bilingual") and (row.heading_en or row.content_en) %}
                <div class="section">
                    <div class="section-heading">
                        {% if row.section_no %}{{ row.section_no }}. {% endif %}{{ row.heading_en or "" }}
                    </div>
                    <div class="sop-body">{{ (row.content_en or "") | safe }}</div>
                </div>
            {% endif %}

            {% if lang in ("Arabic", "Bilingual") and (row.heading_ar or row.content_ar) %}
                <div class="section">
                    <div class="section-heading rtl">
                        {% if row.section_no %}{{ row.section_no }}. {% endif %}{{ row.heading_ar or "" }}
                    </div>
                    <div class="sop-body rtl">{{ (row.content_ar or "") | safe }}</div>
                </div>
            {% endif %}
        {% endfor %}
    {% endif %}

    <div class="revision-title{% if lang == "Arabic" %} title-ar{% endif %}">
        {% if lang == "Arabic" %}سجل المراجعات{% elif lang == "Bilingual" %}Revision History / سجل المراجعات{% else %}Revision History{% endif %}
    </div>
    <table class="revision{% if lang == "Arabic" %} rtl{% endif %}">
        <thead>
            <tr>
                <th>{% if lang == "Arabic" %}الإصدار{% elif lang == "Bilingual" %}Version / الإصدار{% else %}Version{% endif %}</th>
                <th>{% if lang == "Arabic" %}الحالة{% elif lang == "Bilingual" %}Status / الحالة{% else %}Status{% endif %}</th>
                <th>{% if lang == "Arabic" %}تاريخ السريان{% elif lang == "Bilingual" %}Effective Date / تاريخ السريان{% else %}Effective Date{% endif %}</th>
                <th>{% if lang == "Arabic" %}ملخص التغيير{% elif lang == "Bilingual" %}Change Summary / ملخص التغيير{% else %}Change Summary{% endif %}</th>
                <th>{% if lang == "Arabic" %}اعتمد بواسطة{% elif lang == "Bilingual" %}Approved By / اعتمد بواسطة{% else %}Approved By{% endif %}</th>
            </tr>
        </thead>
        <tbody>
        {% for row in versions %}
            <tr>
                <td>{{ row.version_no }}</td>
                <td>{% if lang == "Arabic" %}{{ status_ar.get(row.status, row.status) }}{% else %}{{ row.status }}{% endif %}</td>
                <td>{{ row.effective_from or "" }}</td>
                <td>{{ row.change_summary or "" }}</td>
                <td>{{ row.approved_by or "" }}</td>
            </tr>
        {% endfor %}
        </tbody>
    </table>

    <div class="control-footer{% if lang == "Arabic" %} title-ar{% endif %}">
        {% if lang == "Arabic" %}
            <span>وثيقة خاضعة للرقابة &mdash; مارينا فاشون</span>
            <span>{{ parent.document_no or parent.name }} &middot; الإصدار {{ doc.version_no }}</span>
        {% elif lang == "Bilingual" %}
            <span>Controlled document / وثيقة خاضعة للرقابة &mdash; Marina Fashion / مارينا فاشون</span>
            <span>{{ parent.document_no or parent.name }} &middot; Version / الإصدار {{ doc.version_no }}</span>
        {% else %}
            <span>Controlled document &mdash; Marina Fashion</span>
            <span>{{ parent.document_no or parent.name }} &middot; Version {{ doc.version_no }}</span>
        {% endif %}
    </div>
</div>
"""

    values = {
        "doc_type": "SOP Version",
        "print_format_type": "Jinja",
        "custom_format": 1,
        "disabled": 0,
        "html": html,
    }

    if frappe.db.exists("Print Format", CONTROLLED_PRINT_FORMAT):
        doc = frappe.get_doc("Print Format", CONTROLLED_PRINT_FORMAT)
        for fieldname, value in values.items():
            if doc.meta.has_field(fieldname):
                doc.set(fieldname, value)
        if doc.meta.has_field("module"):
            doc.module = "SOP Management"
        if doc.meta.has_field("standard"):
            doc.standard = "Yes"
        doc.save(ignore_permissions=True)
    else:
        payload = {
            "doctype": "Print Format",
            "name": CONTROLLED_PRINT_FORMAT,
            **values,
        }
        meta = frappe.get_meta("Print Format")
        if meta.has_field("module"):
            payload["module"] = "SOP Management"
        if meta.has_field("standard"):
            payload["standard"] = "Yes"
        frappe.get_doc(payload).insert(ignore_permissions=True)

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
        # The umbrella is a navigation container, not a business module.
        # Leaving its module blank prevents Frappe from rejecting the parent
        # before it evaluates the Workspace Roles table.
        doc.module = ""

        # Workspace roles are an administrator-managed access control. Seed
        # them from JSON on insert, but do not erase later role additions on
        # every app migration.
        for table_field in child_tables:
            if table_field == "roles":
                continue
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

def _sync_workspace_file(workspace_file):
    """Create/update one shipped Workspace without deleting sibling workspaces."""
    if not workspace_file.exists():
        return

    data = json.loads(workspace_file.read_text(encoding="utf-8"))
    name = data["name"]

    child_tables = (
        "links",
        "shortcuts",
        "number_cards",
        "charts",
        "custom_blocks",
        "quick_lists",
        "roles",
    )

    if frappe.db.exists("Workspace", name):
        doc = frappe.get_doc("Workspace", name)
        for fieldname in (
            "label", "title", "module", "icon", "public", "is_hidden",
            "hide_custom", "content", "parent_page", "sequence_id",
        ):
            if fieldname in data:
                doc.set(fieldname, data.get(fieldname))

        # Preserve administrator-managed Workspace Roles on existing sites.
        for table_field in child_tables:
            if table_field == "roles":
                continue
            doc.set(table_field, [])
            for row in data.get(table_field, []):
                doc.append(table_field, row)

        if doc.meta.has_field("standard"):
            doc.standard = 1
        doc.save(ignore_permissions=True)
    else:
        frappe.get_doc(data).insert(ignore_permissions=True)


def sync_module_workspace_hierarchy():
    """Make Marina Custom Apps the parent launcher for Marina module workspaces."""
    if not frappe.db.exists("DocType", "Workspace"):
        return

    base = Path(__file__).resolve().parent

    # SOP Management is owned by this module, so sync its full workspace here.
    # Other specialist workspaces remain owned by their respective modules;
    # below we only enforce their shared parent and approved sequence in DB.
    _sync_workspace_file(
        base / "workspace" / "sop_management" / "sop_management.json"
    )

    workspace_order = (
        ("Marina Calendar", 2.0),
        ("Sales Forecasting", 3.0),
        ("DC Dispatch", 4.0),
        ("Stock Auto Allocation", 5.0),
        ("Stock Transfer Audit", 6.0),
        ("Cycle Count", 7.0),
        ("SOP Management", 8.0),
    )

    # Preserve the approved icons; enforce only hierarchy and exact order.
    for name, sequence_id in workspace_order:
        if frappe.db.exists("Workspace", name):
            frappe.db.set_value(
                "Workspace",
                name,
                {"parent_page": "Marina Custom Apps", "sequence_id": sequence_id},
                update_modified=False,
            )
