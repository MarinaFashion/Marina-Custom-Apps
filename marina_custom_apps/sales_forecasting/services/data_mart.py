import bisect
import hashlib
from collections import defaultdict
from datetime import datetime, time, timedelta

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, getdate, now_datetime

from .common import (
    date_range,
    get_branches,
    is_weekend,
    load_calendar,
    main_groups,
    safe_field,
    salary_phase,
    settings,
    union_hours,
)


DAILY_FIELDS = [
    "name", "owner", "creation", "modified", "modified_by", "docstatus", "idx",
    "record_key", "date", "branch", "warehouse", "main_group", "sub_group",
    "city", "cluster", "store_space", "store_age_days", "store_open_flag", "operating_hours",
    "retail_sales_value", "net_revenue_ex_vat", "net_units", "transaction_count",
    "return_units", "return_value", "avg_realized_price", "realized_discount_pct",
    "displayed_styles", "new_styles_7d", "new_styles_30d", "closing_stock_units",
    "in_stock_skus", "styles_in_stock", "avg_sizes_in_stock_per_style", "avg_markdown_pct",
    "weekday", "is_weekend", "gregorian_month", "hijri_date", "hijri_month_name",
    "hijri_day", "hijri_month", "hijri_year", "event", "salary_phase",
]


def build_data_mart(start_date, end_date, *, commit=True):
    cfg = settings()
    start = getdate(start_date)
    end = getdate(end_date)
    if end < start:
        frappe.throw(_("End Date must be on or after Start Date."))

    branches = get_branches(cfg)
    if not branches:
        frappe.throw(_("No Branch records with a linked selling warehouse were found."))

    groups = main_groups(cfg)
    if not groups:
        frappe.throw(_("Configure at least one Forecast Main Group in Sales Forecast Settings."))

    branch_by_warehouse = {b.warehouse: b for b in branches if b.warehouse}
    warehouses = list(branch_by_warehouse)

    sales = _load_sales(start, end, warehouses, groups, cfg)
    operations = _load_store_operations(start, end, branches, cfg)
    calendar = load_calendar(start, end, cfg)

    item_meta, style_dates, activation, deactivation = _load_item_metadata(start, end, groups, cfg)
    inventory = _InventoryState(start, end, warehouses, item_meta, activation, deactivation, cfg)
    pricing = _PriceState(start, end, item_meta, activation, deactivation, cfg)

    now = now_datetime()
    rows = []
    display_window = max(cint(cfg.displayed_style_window_days or 180), 1)

    style_dates_sorted = {g: sorted(v) for g, v in style_dates.items()}

    for day in date_range(start, end):
        day_key = str(day)
        inventory.advance(day)
        pricing.advance(day, inventory.active_items)
        cal = calendar.get(day_key, {})

        assortment = {}
        for group in groups:
            dates = style_dates_sorted.get(group, [])
            assortment[group] = {
                "displayed_styles": _count_between(dates, day - timedelta(days=display_window - 1), day),
                "new_styles_7d": _count_between(dates, day - timedelta(days=6), day),
                "new_styles_30d": _count_between(dates, day - timedelta(days=29), day),
            }

        for branch in branches:
            if branch.opening_date and getdate(branch.opening_date) > day:
                continue

            operating_hours = flt(operations.get((branch.name, day_key), 0))
            store_age_days = max((day - getdate(branch.opening_date)).days, 0) if branch.opening_date else 0

            for group in groups:
                s = sales.get((branch.warehouse, day_key, group), {})
                transactions = cint(s.get("transaction_count"))
                open_flag = 1 if operating_hours >= 2 or transactions > 0 else 0
                inv = inventory.metrics(branch.warehouse, group)
                published_markdown = pricing.markdown(group)
                positive_units = flt(s.get("positive_units"))
                positive_sales = flt(s.get("positive_sales_value"))
                list_value = flt(s.get("list_value"))

                avg_price = positive_sales / positive_units if positive_units else 0
                realized_discount = (
                    max(0, (list_value - positive_sales) / list_value * 100)
                    if list_value > 0
                    else 0
                )

                record_key = f"{day_key}|{branch.name}|{group}"
                name = "SFD-" + hashlib.sha1(record_key.encode("utf-8")).hexdigest()[:20]
                a = assortment[group]

                row = [
                    name, frappe.session.user or "Administrator", now, now,
                    frappe.session.user or "Administrator", 0, 0,
                    record_key, day_key, branch.name, branch.warehouse, group, "",
                    branch.city or "", branch.cluster or "", flt(branch.store_space), store_age_days,
                    open_flag, operating_hours,
                    flt(s.get("retail_sales_value")), flt(s.get("net_revenue_ex_vat")),
                    flt(s.get("net_units")), transactions, flt(s.get("return_units")),
                    flt(s.get("return_value")), avg_price, realized_discount,
                    a["displayed_styles"], a["new_styles_7d"], a["new_styles_30d"],
                    inv["closing_stock_units"], inv["in_stock_skus"], inv["styles_in_stock"],
                    inv["avg_sizes_in_stock_per_style"], published_markdown,
                    day.strftime("%a"), is_weekend(day), day.month,
                    cal.get("hijri_date") or "", cal.get("hijri_month_name") or "",
                    cint(cal.get("hijri_day")), cint(cal.get("hijri_month")), cint(cal.get("hijri_year")),
                    cal.get("event") or "", salary_phase(day, cfg),
                ]
                rows.append(row)

    _replace_rows(start, end, rows, cfg)
    if commit:
        frappe.db.commit()

    return {
        "start_date": str(start),
        "end_date": str(end),
        "rows": len(rows),
        "branches": len(branches),
        "groups": groups,
    }


def refresh_recent_data():
    cfg = settings()
    lookback = max(cint(cfg.daily_refresh_lookback_days or 14), 1)
    end = getdate(add_days(frappe.utils.today(), -1))
    start = getdate(add_days(end, -(lookback - 1)))
    if start < getdate(cfg.history_start_date):
        start = getdate(cfg.history_start_date)
    return build_data_mart(start, end)


def _load_sales(start, end, warehouses, groups, cfg):
    main_field = safe_field(cfg.item_main_group_field, "custom_item_main_group")
    wh_placeholders = ",".join(["%s"] * len(warehouses))
    group_placeholders = ",".join(["%s"] * len(groups))
    params = [str(start), str(end), *warehouses, *groups]
    rows = frappe.db.sql(
        f"""
        select
            si.posting_date as date,
            sii.warehouse,
            i.`{main_field}` as main_group,
            sum(sii.amount) as retail_sales_value,
            sum(sii.net_amount) as net_revenue_ex_vat,
            sum(sii.qty) as net_units,
            count(distinct si.name) as transaction_count,
            sum(case when sii.qty < 0 then abs(sii.qty) else 0 end) as return_units,
            sum(case when sii.amount < 0 then abs(sii.amount) else 0 end) as return_value,
            sum(case when sii.qty > 0 then sii.qty else 0 end) as positive_units,
            sum(case when sii.qty > 0 then sii.amount else 0 end) as positive_sales_value,
            sum(case when sii.qty > 0 then sii.price_list_rate * sii.qty else 0 end) as list_value
        from `tabSales Invoice Item` sii
        inner join `tabSales Invoice` si on si.name = sii.parent
        inner join `tabItem` i on i.name = sii.item_code
        where si.docstatus = 1
          and si.posting_date between %s and %s
          and sii.warehouse in ({wh_placeholders})
          and i.`{main_field}` in ({group_placeholders})
        group by si.posting_date, sii.warehouse, i.`{main_field}`
        """,
        params,
        as_dict=True,
    )
    return {
        (r.warehouse, str(r.date), r.main_group): r
        for r in rows
    }


def _load_store_operations(start, end, branches, cfg):
    profile_to_branch = {b.pos_profile: b.name for b in branches if b.pos_profile}
    profiles = list(profile_to_branch)
    if not profiles:
        return {}

    placeholders = ",".join(["%s"] * len(profiles))
    start_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(end + timedelta(days=1), time.min)
    rows = frappe.db.sql(
        f"""
        select pos_profile, period_start_date, period_end_date
        from `tabPOS Closing Shift`
        where pos_profile in ({placeholders})
          and period_start_date is not null
          and period_end_date is not null
          and period_end_date >= %s
          and period_start_date < %s
        order by period_start_date asc
        """,
        [*profiles, start_dt, end_dt],
        as_dict=True,
    )

    max_hours = flt(cfg.ignore_pos_shift_over_hours or 24)
    intervals = defaultdict(list)
    for row in rows:
        s = get_datetime(row.period_start_date)
        e = get_datetime(row.period_end_date)
        duration = (e - s).total_seconds() / 3600.0
        if duration <= 0 or (max_hours and duration > max_hours):
            continue
        branch = profile_to_branch.get(row.pos_profile)
        if not branch:
            continue
        d = max(s.date(), start)
        last = min(e.date(), end)
        while d <= last:
            intervals[(branch, str(d))].append((s, e))
            d += timedelta(days=1)

    return {
        key: union_hours(value, key[1])
        for key, value in intervals.items()
    }


def _load_item_metadata(start, end, groups, cfg):
    main_field = safe_field(cfg.item_main_group_field, "custom_item_main_group")
    display_field = safe_field(cfg.item_display_date_field, "display_date")
    window = max(cint(cfg.inventory_active_window_days or 365), cint(cfg.displayed_style_window_days or 180), 30)
    min_display = start - timedelta(days=window)
    group_placeholders = ",".join(["%s"] * len(groups))
    rows = frappe.db.sql(
        f"""
        select name, variant_of, has_variants, `{main_field}` as main_group, `{display_field}` as display_date
        from `tabItem`
        where `{display_field}` is not null
          and `{display_field}` between %s and %s
          and `{main_field}` in ({group_placeholders})
        """,
        [str(min_display), str(end), *groups],
        as_dict=True,
    )

    item_meta = {}
    style_first = {}
    activation = defaultdict(list)
    deactivation = defaultdict(list)
    inv_window = max(cint(cfg.inventory_active_window_days or 365), 1)

    for row in rows:
        display = getdate(row.display_date)
        style = row.variant_of or row.name
        key = (style, row.main_group)
        if key not in style_first or display < style_first[key]:
            style_first[key] = display

        # Templates define styles but do not hold sellable stock. Keep them out of
        # SKU-level inventory/price state to avoid double-counting template + sizes.
        if cint(row.has_variants):
            continue

        item_meta[row.name] = {
            "group": row.main_group,
            "style": style,
            "display_date": display,
            "expiry_date": display + timedelta(days=inv_window - 1),
        }
        if start <= display <= end:
            activation[str(display)].append(row.name)
        expiry_next = display + timedelta(days=inv_window)
        if start <= expiry_next <= end:
            deactivation[str(expiry_next)].append(row.name)

    style_dates = defaultdict(list)
    for (_style, group), display in style_first.items():
        style_dates[group].append(display)

    return item_meta, style_dates, activation, deactivation


class _InventoryState:
    def __init__(self, start, end, warehouses, item_meta, activation, deactivation, cfg):
        self.start = start
        self.end = end
        self.warehouses = warehouses
        self.item_meta = item_meta
        self.activation = activation
        self.deactivation = deactivation
        self.cfg = cfg
        self.item_balance = defaultdict(float)
        self.active_items = set()
        self.stock_units = defaultdict(float)
        self.in_stock_skus = defaultdict(int)
        self.style_balance = defaultdict(float)
        self.styles_in_stock = defaultdict(int)
        self.movements = defaultdict(list)
        self._load()

    def _load(self):
        if not self.item_meta or not self.warehouses:
            return
        cfg = self.cfg
        main_field = safe_field(cfg.item_main_group_field, "custom_item_main_group")
        display_field = safe_field(cfg.item_display_date_field, "display_date")
        groups = main_groups(cfg)
        min_display = self.start - timedelta(days=max(cint(cfg.inventory_active_window_days or 365), 1))
        wh_ph = ",".join(["%s"] * len(self.warehouses))
        group_ph = ",".join(["%s"] * len(groups))

        opening = frappe.db.sql(
            f"""
            select warehouse, item_code, qty_after_transaction
            from (
                select sle.warehouse, sle.item_code, sle.qty_after_transaction,
                       row_number() over (
                           partition by sle.warehouse, sle.item_code
                           order by sle.posting_date desc, sle.posting_time desc, sle.creation desc, sle.name desc
                       ) as rn
                from `tabStock Ledger Entry` sle
                inner join `tabItem` i on i.name = sle.item_code
                where sle.warehouse in ({wh_ph})
                  and sle.posting_date < %s
                  and i.`{display_field}` between %s and %s
                  and i.`{main_field}` in ({group_ph})
            ) x
            where rn = 1
            """,
            [*self.warehouses, str(self.start), str(min_display), str(self.end), *groups],
            as_dict=True,
        )
        for row in opening:
            if row.item_code in self.item_meta:
                self.item_balance[(row.warehouse, row.item_code)] = flt(row.qty_after_transaction)

        movements = frappe.db.sql(
            f"""
            select sle.posting_date, sle.posting_time, sle.creation, sle.name,
                   sle.warehouse, sle.item_code, sle.qty_after_transaction
            from `tabStock Ledger Entry` sle
            inner join `tabItem` i on i.name = sle.item_code
            where sle.warehouse in ({wh_ph})
              and sle.posting_date between %s and %s
              and i.`{display_field}` between %s and %s
              and i.`{main_field}` in ({group_ph})
            order by sle.posting_date asc, sle.posting_time asc, sle.creation asc, sle.name asc
            """,
            [*self.warehouses, str(self.start), str(self.end), str(min_display), str(self.end), *groups],
            as_dict=True,
        )
        for row in movements:
            if row.item_code in self.item_meta:
                self.movements[str(row.posting_date)].append(row)

        for item, meta in self.item_meta.items():
            if meta["display_date"] <= self.start <= meta["expiry_date"]:
                self.active_items.add(item)

        for warehouse in self.warehouses:
            for item in self.active_items:
                qty = self.item_balance.get((warehouse, item), 0)
                if qty > 0:
                    self._add_positive_stock(warehouse, item, qty)

    def advance(self, day):
        key = str(day)
        for item in self.deactivation.get(key, []):
            if item in self.active_items:
                for warehouse in self.warehouses:
                    qty = self.item_balance.get((warehouse, item), 0)
                    if qty > 0:
                        self._remove_positive_stock(warehouse, item, qty)
                self.active_items.discard(item)

        for item in self.activation.get(key, []):
            if item not in self.active_items:
                self.active_items.add(item)
                for warehouse in self.warehouses:
                    qty = self.item_balance.get((warehouse, item), 0)
                    if qty > 0:
                        self._add_positive_stock(warehouse, item, qty)

        for row in self.movements.get(key, []):
            warehouse = row.warehouse
            item = row.item_code
            old = flt(self.item_balance.get((warehouse, item), 0))
            new = flt(row.qty_after_transaction)
            self.item_balance[(warehouse, item)] = new
            if item not in self.active_items:
                continue
            old_pos = max(old, 0)
            new_pos = max(new, 0)
            if old_pos == new_pos:
                continue
            meta = self.item_meta[item]
            group = meta["group"]
            style = meta["style"]
            gkey = (warehouse, group)
            skey = (warehouse, group, style)

            self.stock_units[gkey] += new_pos - old_pos
            if old_pos <= 0 < new_pos:
                self.in_stock_skus[gkey] += 1
            elif old_pos > 0 >= new_pos:
                self.in_stock_skus[gkey] = max(0, self.in_stock_skus[gkey] - 1)

            before_style = self.style_balance[skey]
            after_style = max(0, before_style + (new_pos - old_pos))
            self.style_balance[skey] = after_style
            if before_style <= 0 < after_style:
                self.styles_in_stock[gkey] += 1
            elif before_style > 0 >= after_style:
                self.styles_in_stock[gkey] = max(0, self.styles_in_stock[gkey] - 1)

    def _add_positive_stock(self, warehouse, item, qty):
        meta = self.item_meta[item]
        group, style = meta["group"], meta["style"]
        gkey = (warehouse, group)
        skey = (warehouse, group, style)
        self.stock_units[gkey] += qty
        self.in_stock_skus[gkey] += 1
        before = self.style_balance[skey]
        self.style_balance[skey] = before + qty
        if before <= 0:
            self.styles_in_stock[gkey] += 1

    def _remove_positive_stock(self, warehouse, item, qty):
        meta = self.item_meta[item]
        group, style = meta["group"], meta["style"]
        gkey = (warehouse, group)
        skey = (warehouse, group, style)
        self.stock_units[gkey] = max(0, self.stock_units[gkey] - qty)
        self.in_stock_skus[gkey] = max(0, self.in_stock_skus[gkey] - 1)
        before = self.style_balance[skey]
        after = max(0, before - qty)
        self.style_balance[skey] = after
        if before > 0 >= after:
            self.styles_in_stock[gkey] = max(0, self.styles_in_stock[gkey] - 1)

    def metrics(self, warehouse, group):
        key = (warehouse, group)
        styles = cint(self.styles_in_stock.get(key, 0))
        skus = cint(self.in_stock_skus.get(key, 0))
        return {
            "closing_stock_units": max(0, flt(self.stock_units.get(key, 0))),
            "in_stock_skus": skus,
            "styles_in_stock": styles,
            "avg_sizes_in_stock_per_style": skus / styles if styles else 0,
        }


class _PriceState:
    def __init__(self, start, end, item_meta, activation, deactivation, cfg):
        self.start = start
        self.end = end
        self.item_meta = item_meta
        self.activation = activation
        self.deactivation = deactivation
        self.cfg = cfg
        self.launch_price = {}
        self.current_price = {}
        self.events = defaultdict(list)
        self.markdown_sum = defaultdict(float)
        self.priced_count = defaultdict(int)
        self.item_contribution = {}
        self._load()

    def _load(self):
        if not self.item_meta:
            return
        main_field = safe_field(self.cfg.item_main_group_field, "custom_item_main_group")
        display_field = safe_field(self.cfg.item_display_date_field, "display_date")
        groups = main_groups(self.cfg)
        min_display = self.start - timedelta(days=max(cint(self.cfg.inventory_active_window_days or 365), 1))
        group_ph = ",".join(["%s"] * len(groups))
        rows = frappe.db.sql(
            f"""
            select ip.item_code, ip.price_list_rate, ip.valid_from, ip.creation
            from `tabItem Price` ip
            inner join `tabItem` i on i.name = ip.item_code
            where ip.selling = 1
              and ip.price_list = %s
              and ip.valid_from <= %s
              and i.`{display_field}` between %s and %s
              and i.`{main_field}` in ({group_ph})
            order by ip.item_code asc, ip.valid_from asc, ip.creation asc
            """,
            [self.cfg.selling_price_list or "Standard Selling", str(self.end), str(min_display), str(self.end), *groups],
            as_dict=True,
        )
        for row in rows:
            item = row.item_code
            if item not in self.item_meta or flt(row.price_list_rate) <= 0:
                continue
            if item not in self.launch_price:
                self.launch_price[item] = flt(row.price_list_rate)
            valid = getdate(row.valid_from)
            if valid < self.start:
                self.current_price[item] = flt(row.price_list_rate)
            else:
                self.events[str(valid)].append((item, flt(row.price_list_rate)))

        # Initialize contribution for items active on the first day.
        for item, meta in self.item_meta.items():
            if meta["display_date"] <= self.start <= meta["expiry_date"]:
                self._activate(item)

    def advance(self, day, active_items):
        key = str(day)
        for item in self.deactivation.get(key, []):
            self._deactivate(item)
        for item in self.activation.get(key, []):
            self._activate(item)
        for item, price in self.events.get(key, []):
            self.current_price[item] = price
            if item in active_items:
                self._refresh_contribution(item)

    def _markdown(self, item):
        launch = flt(self.launch_price.get(item))
        current = flt(self.current_price.get(item))
        if launch <= 0 or current <= 0:
            return None
        return max(0.0, (launch - current) / launch * 100.0)

    def _activate(self, item):
        if item in self.item_contribution:
            return
        md = self._markdown(item)
        if md is None:
            return
        group = self.item_meta[item]["group"]
        self.item_contribution[item] = md
        self.markdown_sum[group] += md
        self.priced_count[group] += 1

    def _deactivate(self, item):
        if item not in self.item_contribution:
            return
        group = self.item_meta[item]["group"]
        self.markdown_sum[group] -= self.item_contribution.pop(item)
        self.priced_count[group] = max(0, self.priced_count[group] - 1)

    def _refresh_contribution(self, item):
        group = self.item_meta[item]["group"]
        old = self.item_contribution.get(item)
        md = self._markdown(item)
        if old is None and md is not None:
            self.item_contribution[item] = md
            self.markdown_sum[group] += md
            self.priced_count[group] += 1
        elif old is not None and md is not None:
            self.item_contribution[item] = md
            self.markdown_sum[group] += md - old

    def markdown(self, group):
        count = cint(self.priced_count.get(group, 0))
        return self.markdown_sum.get(group, 0) / count if count else 0


def _count_between(sorted_dates, start, end):
    return bisect.bisect_right(sorted_dates, end) - bisect.bisect_left(sorted_dates, start)


def _replace_rows(start, end, rows, cfg):
    frappe.db.sql(
        "delete from `tabSales Forecast Daily` where `date` between %s and %s",
        (str(start), str(end)),
    )
    if not rows:
        return
    chunk = max(cint(cfg.data_mart_batch_size or 5000), 500)
    frappe.db.bulk_insert(
        "Sales Forecast Daily",
        fields=DAILY_FIELDS,
        values=rows,
        ignore_duplicates=False,
        chunk_size=chunk,
    )
