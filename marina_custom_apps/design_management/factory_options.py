"""Factory master choices, validation and one-time legacy settings migration."""
import frappe


MAX_FACTORIES = 200
MAX_HISTORIC_CHOICES = 500


def parse_factory_list(raw):
    """Pure, deterministic parser; tests can execute it without Frappe."""
    names = []
    seen = set()
    for raw_name in (raw or "").splitlines():
        name = raw_name.strip()
        if not name:
            continue
        if any(ord(char) < 32 or ord(char) == 127 for char in name):
            raise ValueError("Factory names cannot contain control characters")
        if len(name) > 140:
            raise ValueError("Factory names cannot exceed 140 characters: " + name[:60])
        key = name.casefold()
        if key in seen:
            raise ValueError("Duplicate Factory in Settings: " + name)
        seen.add(key)
        names.append(name)
        if len(names) > MAX_FACTORIES:
            raise ValueError("Factory List supports at most {} names".format(MAX_FACTORIES))
    return names


def configured_factory_choices():
    """Cache active master names within this request only."""
    cached = getattr(frappe.local, "_marina_factory_choice_cache", None)
    if cached is not None:
        return list(cached)
    choices = frappe.get_all("Factory List", filters={"is_active": 1},
        pluck="name", order_by="name asc", limit_page_length=1001)
    if len(choices) > 1000:
        frappe.throw("Factory List supports at most 1,000 active factories")
    frappe.local._marina_factory_choice_cache = tuple(choices)
    return choices


def historical_factory_choices():
    """Only used on rare Settings changes/migration, not per form request."""
    names = set()
    for doctype, field in (("Design Code", "factory"),):
        if not frappe.db.exists("DocType", doctype):
            continue
        if not frappe.get_meta(doctype).has_field(field):
            continue
        values = frappe.db.sql(
            "SELECT DISTINCT `{field}` FROM `tab{doctype}` "
            "WHERE `{field}` IS NOT NULL AND `{field}`!='' "
            "LIMIT {limit}".format(
                field=field, doctype=doctype, limit=MAX_HISTORIC_CHOICES + 1
            )
        )
        if len(values) > MAX_HISTORIC_CHOICES:
            frappe.throw(
                "Factory history has more than {} distinct values; "
                "review the Factory Select migration before updating settings."
                .format(MAX_HISTORIC_CHOICES)
            )
        names.update(str(row[0]).strip() for row in values if row[0])
    return sorted(name for name in names if name)


def migrate_factory_master():
    """Preserve legacy names and never overwrite existing master records."""
    if not frappe.db.exists("DocType", "Factory List"):
        return
    if not frappe.db.get_single_value("Design Management Settings", "factory_master_migrated"):
        active = parse_factory_list(frappe.db.get_single_value(
            "Design Management Settings", "factory_list") or "")
        active_set = set(active)
        for name in dict.fromkeys(active + historical_factory_choices()):
            if not frappe.db.exists("Factory List", name):
                frappe.get_doc({"doctype": "Factory List", "factory_name": name,
                    "is_active": int(name in active_set)}).insert(ignore_permissions=True)
        frappe.db.set_single_value("Design Management Settings", "factory_master_migrated", 1)
    # Retire the Select-options override so the standard Link points to its master.
    for prop in ("options", "fieldtype"):
        rows = frappe.get_all("Property Setter", filters={"doc_type": "Design Code",
            "field_name": "factory", "property": prop}, pluck="name")
        for name in rows:
            frappe.delete_doc("Property Setter", name, ignore_permissions=True)
    frappe.clear_cache(doctype="Design Code")
    if hasattr(frappe.local, "_marina_factory_choice_cache"):
        delattr(frappe.local, "_marina_factory_choice_cache")


def check_factory(value, *, mandatory=False, existing_value=None):
    """Server validation; active new values only, historical unchanged allowed."""
    value = (value or "").strip()
    if mandatory and not value:
        frappe.throw("Select Factory before activating external factory work")
    if not value:
        return ""
    if value in configured_factory_choices():
        return value
    if existing_value and value == str(existing_value).strip():
        return value
    frappe.throw(
        "Factory '{}' is not active in Factory List. "
        "Choose an active factory or update its Factory List record.".format(value)
    )


@frappe.whitelist()
def get_factory_options():
    """Form picker for new and existing Design Codes; excludes retired values."""
    if not (frappe.has_permission("Design Code", "read")
            or frappe.has_permission("Design Code", "create")):
        frappe.throw("Not authorized to view Factory choices", frappe.PermissionError)
    return configured_factory_choices()

