import math
import re
from collections import defaultdict
from datetime import datetime, timedelta

import frappe
from frappe.utils import add_days, cint, flt, getdate


_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def settings():
    return frappe.get_single("Sales Forecast Settings")


def safe_field(value, fallback=None):
    value = (value or fallback or "").strip()
    if not _FIELD_RE.match(value):
        frappe.throw(f"Unsafe configured fieldname: {value}")
    return value


def main_groups(cfg=None):
    cfg = cfg or settings()
    return [x.strip() for x in (cfg.main_groups or "Dresses,Uppers,Bottoms").split(",") if x.strip()]


def date_range(start_date, end_date):
    start = getdate(start_date)
    end = getdate(end_date)
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def salary_phase(date_value, cfg=None):
    cfg = cfg or settings()
    d = getdate(date_value).day
    pre = cint(cfg.salary_pre_start_day or 25)
    peak = cint(cfg.salary_peak_start_day or 27)
    peak_next = cint(cfg.salary_peak_end_next_month_day or 3)
    decline_end = cint(cfg.salary_decline_end_day or 9)
    if d >= peak or d <= peak_next:
        return "Salary Peak"
    if d >= pre:
        return "Pre-Salary"
    if peak_next < d <= decline_end:
        return "Post-Salary Decline"
    return "Normal"


def is_weekend(date_value):
    # Saudi weekend: Friday/Saturday.
    return 1 if getdate(date_value).weekday() in (4, 5) else 0


def get_branches(cfg=None):
    cfg = cfg or settings()
    fields = {
        "company": safe_field(cfg.branch_company_field, "custom_company"),
        "opening_date": safe_field(cfg.branch_opening_date_field, "custom_opening_date"),
        "store_space": safe_field(cfg.branch_store_space_field, "custom_store_space"),
        "cluster": safe_field(cfg.branch_cluster_field, "custom_cluster"),
        "warehouse": safe_field(cfg.branch_warehouse_field, "custom_warehouse"),
        "pos_profile": safe_field(cfg.branch_pos_profile_field, "custom_pos_profile"),
        "city": safe_field(cfg.branch_city_field, "custom_city"),
    }
    company_clause = f"where `{fields['company']}` = %s" if cfg.company else ""
    params = [cfg.company] if cfg.company else []
    rows = frappe.db.sql(
        f"""
        select name,
               `{fields['opening_date']}` as opening_date,
               `{fields['store_space']}` as store_space,
               `{fields['cluster']}` as cluster,
               `{fields['warehouse']}` as warehouse,
               `{fields['pos_profile']}` as pos_profile,
               `{fields['city']}` as city
        from `tabBranch`
        {company_clause}
        order by name asc
        """,
        params,
        as_dict=True,
    )
    return [r for r in rows if r.warehouse]


def detect_calendar_doctype(cfg=None):
    cfg = cfg or settings()
    if cfg.calendar_doctype and frappe.db.exists("DocType", cfg.calendar_doctype):
        return cfg.calendar_doctype

    required = [
        safe_field(cfg.calendar_date_field, "date"),
        safe_field(cfg.calendar_event_field, "event"),
        safe_field(cfg.calendar_hijri_date_field, "hijri_date"),
        safe_field(cfg.calendar_hijri_day_field, "day"),
        safe_field(cfg.calendar_hijri_month_field, "month"),
        safe_field(cfg.calendar_hijri_year_field, "year"),
    ]
    placeholders = ", ".join(["%s"] * len(required))
    candidates = frappe.db.sql(
        f"""
        select parent, count(distinct fieldname) as score
        from `tabDocField`
        where fieldname in ({placeholders})
        group by parent
        order by score desc, parent asc
        limit 10
        """,
        required,
        as_dict=True,
    )
    if candidates and cint(candidates[0].score) >= len(required):
        name = candidates[0].parent
        frappe.db.set_single_value("Sales Forecast Settings", "calendar_doctype", name)
        cfg.calendar_doctype = name
        return name
    return None


def load_calendar(start_date, end_date, cfg=None):
    cfg = cfg or settings()
    doctype = detect_calendar_doctype(cfg)
    if not doctype:
        return {}

    meta = frappe.get_meta(doctype)
    mapping = {
        "date": safe_field(cfg.calendar_date_field, "date"),
        "event": safe_field(cfg.calendar_event_field, "event"),
        "hijri_date": safe_field(cfg.calendar_hijri_date_field, "hijri_date"),
        "hijri_month_name": safe_field(cfg.calendar_hijri_month_name_field, "hijri_m_name"),
        "hijri_day": safe_field(cfg.calendar_hijri_day_field, "day"),
        "hijri_month": safe_field(cfg.calendar_hijri_month_field, "month"),
        "hijri_year": safe_field(cfg.calendar_hijri_year_field, "year"),
    }
    available = {f.fieldname for f in meta.fields}
    if mapping["date"] not in available:
        return {}

    fields = [mapping["date"]]
    for key in ("event", "hijri_date", "hijri_month_name", "hijri_day", "hijri_month", "hijri_year"):
        if mapping[key] in available:
            fields.append(mapping[key])

    rows = frappe.get_all(
        doctype,
        filters={mapping["date"]: ["between", [start_date, end_date]]},
        fields=fields,
        order_by=f"{mapping['date']} asc",
        limit_page_length=0,
    )
    out = {}
    for row in rows:
        key = str(row.get(mapping["date"]))
        out[key] = {
            "event": row.get(mapping["event"]) if mapping["event"] in available else "",
            "hijri_date": row.get(mapping["hijri_date"]) if mapping["hijri_date"] in available else "",
            "hijri_month_name": row.get(mapping["hijri_month_name"]) if mapping["hijri_month_name"] in available else "",
            "hijri_day": cint(row.get(mapping["hijri_day"])) if mapping["hijri_day"] in available else 0,
            "hijri_month": cint(row.get(mapping["hijri_month"])) if mapping["hijri_month"] in available else 0,
            "hijri_year": cint(row.get(mapping["hijri_year"])) if mapping["hijri_year"] in available else 0,
        }
    return out


def union_hours(intervals, day):
    if not intervals:
        return 0.0
    day = getdate(day)
    day_start = datetime.combine(day, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    clipped = []
    for start, end in intervals:
        start = max(start, day_start)
        end = min(end, day_end)
        if end > start:
            clipped.append((start, end))
    if not clipped:
        return 0.0
    clipped.sort(key=lambda x: x[0])
    merged = [list(clipped[0])]
    for start, end in clipped[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return sum((end - start).total_seconds() for start, end in merged) / 3600.0


def exp_recency_weight(age_days, half_life_days):
    half_life_days = max(flt(half_life_days), 1)
    return math.exp(-math.log(2) * max(flt(age_days), 0) / half_life_days)
