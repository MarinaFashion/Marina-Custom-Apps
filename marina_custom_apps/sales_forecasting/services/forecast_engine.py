import hashlib
import json
import math
from collections import defaultdict
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, now_datetime

from .common import (
    calendar_context,
    exp_recency_weight,
    get_branches,
    is_weekend,
    load_calendar,
    main_groups,
    salary_phase,
    settings,
)


RESULT_FIELDS = [
    "name", "owner", "creation", "modified", "modified_by", "docstatus", "idx",
    "result_key", "forecast_run", "date", "branch", "main_group",
    "forecast_sales", "forecast_sales_low", "forecast_sales_high", "forecast_units",
    "forecast_asp", "confidence_pct", "actual_sales", "actual_units", "absolute_error",
    "signed_error", "absolute_pct_error", "analog_samples", "drivers",
]


def run_forecast(run_name, *, commit=True):
    cfg = settings()
    run = frappe.get_doc("Sales Forecast Run", run_name)
    _validate_run(run)

    _set_run(run.name, status="Running", error_message="")
    if commit:
        frappe.db.commit()

    try:
        as_of = getdate(run.as_of_date)
        forecast_from = getdate(run.forecast_from)
        forecast_to = getdate(run.forecast_to)
        lookback_years = max(cint(cfg.lookback_years or 3), 1)
        history_from = as_of - timedelta(days=lookback_years * 366)
        history_to = as_of

        branches = get_branches(cfg)
        if run.branch:
            branches = [b for b in branches if b.name == run.branch]
        groups = [run.main_group] if run.main_group else main_groups(cfg)
        if not branches or not groups:
            frappe.throw(_("No branches or groups match the forecast scope."))

        history = _load_history(history_from, history_to, groups)
        pools = _build_pools(history)
        calendar = load_calendar(forecast_from, forecast_to, cfg)
        plan = (
            _resolve_plan(run, as_of, forecast_from, forecast_to)
            if cint(cfg.apply_buying_plan_adjustment)
            else None
        )
        plan_context = _plan_context(plan, as_of, cfg) if plan else {}

        actual_map = _load_actuals(forecast_from, forecast_to, [b.name for b in branches], groups)
        latest_context = _latest_context(history)

        rows = []
        total_forecast_sales = total_forecast_units = 0.0
        total_actual_sales = total_actual_units = 0.0
        total_abs_error = total_signed_error = 0.0
        actual_rows = 0
        now = now_datetime()

        day = forecast_from
        while day <= forecast_to:
            cal = calendar.get(str(day), {})
            target = {
                "date": day,
                "weekday": day.strftime("%a"),
                "is_weekend": is_weekend(day),
                "gregorian_month": day.month,
                "salary_phase": salary_phase(day, cfg),
                "hijri_day": cint(cal.get("hijri_day")),
                "hijri_month": cint(cal.get("hijri_month")),
                "event": cal.get("event") or "",
                "as_of_date": as_of,
            }
            for branch in branches:
                if branch.opening_date and getdate(branch.opening_date) > day:
                    continue
                for group in groups:
                    cal_ctx = calendar_context(cal, branch, group, cfg.company)
                    target["hijri_day"] = cint(cal_ctx.get("hijri_day"))
                    target["hijri_month"] = cint(cal_ctx.get("hijri_month"))
                    target["event"] = cal_ctx.get("event") or ""
                    target["store_trading_status"] = cal_ctx.get("store_trading_status") or "No Change"
                    plan_features = _plan_features(plan_context, group, day)
                    recent = latest_context.get((branch.name, group), {})
                    target["new_styles_30d"] = (
                        plan_features.get("new_styles_30d")
                        if plan_features.get("new_styles_30d") is not None
                        else cint(recent.get("new_styles_30d"))
                    )
                    target["target_markdown_pct"] = 0.0 if plan_features.get("new_styles_30d", 0) else flt(recent.get("avg_markdown_pct"))

                    candidates, fallback = _candidate_pool(
                        pools, branch, group, cint(cfg.minimum_analog_samples or 20)
                    )
                    if target["store_trading_status"] == "Closed":
                        pred = {
                            "forecast_sales": 0, "forecast_units": 0, "forecast_asp": 0,
                            "low": 0, "high": 0, "confidence": 95, "samples": 0,
                            "drivers": {
                                "fallback": fallback,
                                "store_trading_status": "Closed",
                                "event": target.get("event") or None,
                                "rule": "Explicit calendar closure",
                            },
                        }
                    else:
                        pred = _predict_one(candidates, target, branch, fallback, cfg, plan_features)
                        if target["store_trading_status"] == "Partially Open":
                            pred["confidence"] = max(10, pred["confidence"] - 15)
                            pred["drivers"]["store_trading_status"] = "Partially Open"
                            pred["drivers"]["warning"] = "Partial operation; no automatic sales multiplier applied"
                    actual = actual_map.get((str(day), branch.name, group))

                    actual_sales = flt(actual.get("retail_sales_value")) if actual else 0
                    actual_units = flt(actual.get("net_units")) if actual else 0
                    has_actual = actual is not None
                    abs_error = abs(pred["forecast_sales"] - actual_sales) if has_actual else 0
                    signed_error = pred["forecast_sales"] - actual_sales if has_actual else 0
                    ape = abs_error / abs(actual_sales) * 100 if has_actual and actual_sales else 0

                    key = f"{run.name}|{day}|{branch.name}|{group}"
                    name = "SFRS-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
                    rows.append([
                        name, frappe.session.user or "Administrator", now, now,
                        frappe.session.user or "Administrator", 0, 0,
                        key, run.name, str(day), branch.name, group,
                        pred["forecast_sales"], pred["low"], pred["high"], pred["forecast_units"],
                        pred["forecast_asp"], pred["confidence"], actual_sales if has_actual else None,
                        actual_units if has_actual else None, abs_error if has_actual else None,
                        signed_error if has_actual else None, ape if has_actual else None,
                        pred["samples"], json.dumps(pred["drivers"], ensure_ascii=False),
                    ])
                    total_forecast_sales += pred["forecast_sales"]
                    total_forecast_units += pred["forecast_units"]
                    if has_actual:
                        total_actual_sales += actual_sales
                        total_actual_units += actual_units
                        total_abs_error += abs_error
                        total_signed_error += signed_error
                        actual_rows += 1
            day += timedelta(days=1)

        frappe.db.delete("Sales Forecast Result", {"forecast_run": run.name})
        if rows:
            frappe.db.bulk_insert(
                "Sales Forecast Result",
                fields=RESULT_FIELDS,
                values=rows,
                ignore_duplicates=False,
                chunk_size=5000,
            )

        wape = total_abs_error / abs(total_actual_sales) * 100 if total_actual_sales else 0
        bias = total_signed_error / abs(total_actual_sales) * 100 if total_actual_sales else 0
        mae = total_abs_error / actual_rows if actual_rows else 0
        accuracy = max(0, 100 - wape) if actual_rows else 0

        _set_run(
            run.name,
            status="Completed",
            model_name=cfg.model_name or "Marina Analog Ensemble v1",
            generated_on=now,
            history_from=str(history_from),
            history_to=str(history_to),
            forecast_sales=total_forecast_sales,
            forecast_units=total_forecast_units,
            actual_sales=total_actual_sales if actual_rows else 0,
            actual_units=total_actual_units if actual_rows else 0,
            wape=wape if actual_rows else 0,
            accuracy_pct=accuracy if actual_rows else 0,
            bias_pct=bias if actual_rows else 0,
            mae=mae if actual_rows else 0,
            result_count=len(rows),
            error_message="",
        )
        if commit:
            frappe.db.commit()
        return {
            "run": run.name,
            "results": len(rows),
            "forecast_sales": total_forecast_sales,
            "wape": wape if actual_rows else None,
            "bias": bias if actual_rows else None,
        }
    except Exception:
        message = frappe.get_traceback()
        _set_run(run.name, status="Failed", error_message=message[-4000:])
        frappe.db.commit()
        raise


def _validate_run(run):
    start = getdate(run.forecast_from)
    end = getdate(run.forecast_to)
    as_of = getdate(run.as_of_date)
    if end < start:
        frappe.throw(_("Forecast To must be on or after Forecast From."))
    if run.run_type == "Backtest" and start <= as_of:
        frappe.throw(_("For Backtest, Forecast From must be after Information Available Through."))
    if run.buying_plan:
        plan = frappe.get_doc("Forecast Buying Plan", run.buying_plan)
        if plan.docstatus != 1 or plan.status not in ("Approved", "Superseded"):
            frappe.throw(_("Selected Buying Plan must be submitted and approved."))
        if plan.effective_from and getdate(plan.effective_from) > as_of:
            frappe.throw(_("Selected Buying Plan was not yet effective on the Information Available Through date."))


def _set_run(name, **values):
    frappe.db.set_value("Sales Forecast Run", name, values, update_modified=True)


def _load_history(start, end, groups):
    return frappe.get_all(
        "Sales Forecast Daily",
        filters={"date": ["between", [str(start), str(end)]], "main_group": ["in", groups]},
        fields=[
            "date", "branch", "main_group", "city", "cluster", "store_space", "store_open_flag",
            "retail_sales_value", "net_units", "transaction_count", "avg_realized_price",
            "realized_discount_pct", "displayed_styles", "new_styles_7d", "new_styles_30d",
            "closing_stock_units", "in_stock_skus", "styles_in_stock", "avg_sizes_in_stock_per_style",
            "avg_markdown_pct", "weekday", "is_weekend", "gregorian_month", "hijri_day",
            "hijri_month", "event", "store_trading_status", "salary_phase",
        ],
        order_by="date asc",
        limit_page_length=0,
    )


def _build_pools(history):
    pools = {
        "branch": defaultdict(list),
        "cluster": defaultdict(list),
        "city": defaultdict(list),
        "company": defaultdict(list),
    }
    for row in history:
        if (row.store_trading_status or "No Change") == "Closed":
            continue
        if not cint(row.store_open_flag) and not cint(row.transaction_count):
            continue
        group = row.main_group
        pools["branch"][(row.branch, group)].append(row)
        if row.cluster:
            pools["cluster"][(row.cluster, group)].append(row)
        if row.city:
            pools["city"][(row.city, group)].append(row)
        pools["company"][group].append(row)
    return pools


def _candidate_pool(pools, branch, group, minimum):
    rows = pools["branch"].get((branch.name, group), [])
    if len(rows) >= minimum:
        return rows, "Branch"
    if branch.cluster:
        rows = pools["cluster"].get((branch.cluster, group), [])
        if len(rows) >= minimum:
            return rows, "Cluster"
    if branch.city:
        rows = pools["city"].get((branch.city, group), [])
        if len(rows) >= minimum:
            return rows, "City"
    return pools["company"].get(group, []), "Company"


def _predict_one(candidates, target, branch, fallback, cfg, plan_features):
    if not candidates:
        return {
            "forecast_sales": 0, "forecast_units": 0, "forecast_asp": 0,
            "low": 0, "high": 0, "confidence": 0, "samples": 0,
            "drivers": {"fallback": fallback, "warning": "No historical analogs"},
        }

    weighted = []
    target_date = target["date"]
    half_life = cint(cfg.recency_half_life_days or 365)
    target_new = flt(target.get("new_styles_30d"))
    target_markdown = flt(target.get("target_markdown_pct"))

    for row in candidates:
        age = (target_date - getdate(row.date)).days
        w = exp_recency_weight(age, half_life)
        if row.weekday == target["weekday"]:
            w *= 2.5
        elif cint(row.is_weekend) == cint(target["is_weekend"]):
            w *= 1.25
        if row.salary_phase == target["salary_phase"]:
            w *= 1.45
        if cint(target.get("hijri_month")) and cint(row.hijri_month) == cint(target["hijri_month"]):
            w *= 1.8
            if cint(target.get("hijri_day")) and cint(row.hijri_day):
                dist = abs(cint(row.hijri_day) - cint(target["hijri_day"]))
                w *= 1 + math.exp(-dist / 5.0)
        elif cint(row.gregorian_month) == cint(target["gregorian_month"]):
            w *= 1.1
        if target["event"] and row.event == target["event"]:
            w *= 1.6
        elif not target["event"] and not row.event:
            w *= 1.05

        if target_new > 0:
            diff = abs(flt(row.new_styles_30d) - target_new)
            w *= 0.35 + 0.65 * math.exp(-diff / max(target_new, 5))
        markdown_diff = abs(flt(row.avg_markdown_pct) - target_markdown)
        w *= 0.5 + 0.5 * math.exp(-markdown_diff / 15.0)

        if flt(row.closing_stock_units) <= 0 and flt(row.retail_sales_value) <= 0:
            w *= 0.15
        weighted.append((row, max(w, 0.000001)))

    # Keep the strongest analogs so distant periods do not swamp the model.
    weighted.sort(key=lambda x: x[1], reverse=True)
    sample_limit = max(60, cint(cfg.minimum_analog_samples or 20) * 4)
    weighted = weighted[:sample_limit]
    total_w = sum(w for _, w in weighted)

    mean_units = sum(flt(r.net_units) * w for r, w in weighted) / total_w
    mean_sales = sum(flt(r.retail_sales_value) * w for r, w in weighted) / total_w
    mean_asp = (
        sum(flt(r.avg_realized_price) * w for r, w in weighted if flt(r.avg_realized_price) > 0)
        / max(sum(w for r, w in weighted if flt(r.avg_realized_price) > 0), 0.000001)
    )

    trend = _trend_factor(candidates, getdate(target.get("as_of_date")))
    scale = 1.0
    if fallback != "Branch" and flt(branch.store_space) > 0:
        avg_space = sum(flt(r.store_space) * w for r, w in weighted if flt(r.store_space) > 0) / max(
            sum(w for r, w in weighted if flt(r.store_space) > 0), 0.000001
        )
        if avg_space > 0:
            scale = min(1.4, max(0.6, flt(branch.store_space) / avg_space))

    forecast_units = max(0, mean_units * trend * scale)
    plan_asp = flt(plan_features.get("planned_asp"))
    forecast_asp = plan_asp if plan_asp > 0 else max(mean_asp, 0)
    if forecast_asp > 0:
        forecast_sales = forecast_units * forecast_asp
    else:
        forecast_sales = max(0, mean_sales * trend * scale)
        forecast_asp = forecast_sales / forecast_units if forecast_units else 0

    unit_var = sum(w * (flt(r.net_units) - mean_units) ** 2 for r, w in weighted) / total_w
    unit_sd = math.sqrt(max(unit_var, 0)) * trend * scale
    z = flt(cfg.confidence_z or 1.28)
    sales_sd = unit_sd * forecast_asp if forecast_asp else math.sqrt(
        max(sum(w * (flt(r.retail_sales_value) - mean_sales) ** 2 for r, w in weighted) / total_w, 0)
    )
    low = max(0, forecast_sales - z * sales_sd)
    high = max(forecast_sales, forecast_sales + z * sales_sd)

    cv = sales_sd / max(forecast_sales, 1)
    confidence = min(95, 50 + min(len(weighted), 60) * 0.7) - min(35, cv * 25)
    receipt = plan_features.get("receipt_completion_pct")
    if receipt is not None and (target_date - getdate(target.get("as_of_date"))).days <= 14 and flt(receipt) < 80:
        confidence -= min(20, (80 - flt(receipt)) / 4)
    confidence = max(10, min(95, confidence))

    return {
        "forecast_sales": forecast_sales,
        "forecast_units": forecast_units,
        "forecast_asp": forecast_asp,
        "low": low,
        "high": high,
        "confidence": confidence,
        "samples": len(weighted),
        "drivers": {
            "fallback": fallback,
            "trend_factor": round(trend, 4),
            "store_space_factor": round(scale, 4),
            "salary_phase": target["salary_phase"],
            "hijri_month": target.get("hijri_month") or None,
            "event": target.get("event") or None,
            "store_trading_status": target.get("store_trading_status") or "No Change",
            "planned_new_styles_30d": plan_features.get("new_styles_30d"),
            "planned_asp": plan_asp or None,
            "po_completion_pct": plan_features.get("po_completion_pct"),
            "receipt_completion_pct": plan_features.get("receipt_completion_pct"),
        },
    }


def _trend_factor(candidates, target_date):
    recent_from = target_date - timedelta(days=56)
    prior_from = target_date - timedelta(days=112)
    recent = [flt(r.retail_sales_value) for r in candidates if recent_from <= getdate(r.date) < target_date]
    prior = [flt(r.retail_sales_value) for r in candidates if prior_from <= getdate(r.date) < recent_from]
    if not recent or not prior:
        return 1.0
    a = sum(recent) / len(recent)
    b = sum(prior) / len(prior)
    if b <= 0:
        return 1.0
    return min(1.2, max(0.8, a / b))


def _latest_context(history):
    out = {}
    for row in history:
        out[(row.branch, row.main_group)] = row
    return out


def _resolve_plan(run, as_of, forecast_from, forecast_to):
    if run.buying_plan and frappe.db.exists("Forecast Buying Plan", run.buying_plan):
        return frappe.get_doc("Forecast Buying Plan", run.buying_plan)

    names = frappe.db.sql(
        """
        select distinct p.name
        from `tabForecast Buying Plan` p
        inner join `tabForecast Buying Plan Item` i on i.parent = p.name
        where p.docstatus = 1
          and p.status in ('Approved', 'Superseded')
          and p.effective_from <= %s
          and i.display_date between %s and %s
        order by p.effective_from desc, p.version desc
        limit 1
        """,
        (str(as_of), str(forecast_from - timedelta(days=60)), str(forecast_to)),
    )
    return frappe.get_doc("Forecast Buying Plan", names[0][0]) if names else None


def _plan_context(plan, as_of, cfg):
    """Build buying-plan context using only execution known by ``as_of``.

    The Buying Plan stores today's readiness for operational use, but a historical
    backtest must not see POs or receipts created after its information cut-off.
    This method recomputes PO/receipt progress as-of the run date to prevent
    future-data leakage.
    """
    context = defaultdict(list)
    if not plan:
        return context

    for row in plan.items:
        execution = _execution_as_of(plan, row, as_of, cfg)
        planned_qty = flt(row.planned_total_qty)
        po_pct = min(100, execution["po_qty"] / planned_qty * 100) if planned_qty else 0
        receipt_pct = min(100, execution["received_qty"] / planned_qty * 100) if planned_qty else 0
        context[row.main_group].append({
            "display_date": getdate(row.display_date),
            "styles": flt(row.planned_styles),
            "qty": planned_qty,
            "selling": flt(row.planned_selling_value),
            "po_completion_pct": po_pct,
            "receipt_completion_pct": receipt_pct,
        })
    return context


def _execution_as_of(plan, row, as_of, cfg):
    from .common import safe_field

    item_year = safe_field(cfg.item_year_field, "item_year")
    item_season = safe_field(cfg.item_season_field, "season")
    item_collection = safe_field(cfg.item_collection_field, "collection")
    item_drop = safe_field(cfg.item_drop_field, "custom_drop")
    item_display = safe_field(cfg.item_display_date_field, "display_date")
    item_group = safe_field(cfg.item_main_group_field, "custom_item_main_group")
    supplier = cfg.buying_supplier or "Midmak"

    classification = [
        str(plan.plan_year), plan.season, row.collection, row.drop,
        str(row.display_date), row.main_group,
    ]
    where = f"""
        i.`{item_year}` = %s
        and i.`{item_season}` = %s
        and i.`{item_collection}` = %s
        and i.`{item_drop}` = %s
        and i.`{item_display}` = %s
        and i.`{item_group}` = %s
    """

    po_qty = frappe.db.sql(
        f"""
        select coalesce(sum(poi.qty), 0)
        from `tabPurchase Order Item` poi
        inner join `tabPurchase Order` po on po.name = poi.parent
        inner join `tabItem` i on i.name = poi.item_code
        where po.docstatus = 1
          and po.supplier = %s
          and po.transaction_date <= %s
          and date(po.creation) <= %s
          and {where}
        """,
        [supplier, str(as_of), str(as_of), *classification],
    )[0][0] or 0

    received_qty = frappe.db.sql(
        f"""
        select coalesce(sum(pri.qty), 0)
        from `tabPurchase Receipt Item` pri
        inner join `tabPurchase Receipt` pr on pr.name = pri.parent
        inner join `tabItem` i on i.name = pri.item_code
        where pr.docstatus = 1
          and pr.supplier = %s
          and pr.posting_date <= %s
          and date(pr.creation) <= %s
          and {where}
        """,
        [supplier, str(as_of), str(as_of), *classification],
    )[0][0] or 0

    return {"po_qty": flt(po_qty), "received_qty": flt(received_qty)}


def _plan_features(context, group, day):
    rows = context.get(group, [])
    if not rows:
        return {}
    last30 = [r for r in rows if day - timedelta(days=29) <= r["display_date"] <= day]
    active90 = [r for r in rows if day - timedelta(days=89) <= r["display_date"] <= day]
    future14 = [r for r in rows if day <= r["display_date"] <= day + timedelta(days=14)]
    qty = sum(r["qty"] for r in active90)
    selling = sum(r["selling"] for r in active90)
    relevant = active90 or future14
    if not relevant:
        return {"new_styles_30d": sum(r["styles"] for r in last30)}
    weight = sum(max(r["qty"], 1) for r in relevant)
    return {
        "new_styles_30d": sum(r["styles"] for r in last30),
        "planned_asp": selling / qty if qty else None,
        "po_completion_pct": sum(r["po_completion_pct"] * max(r["qty"], 1) for r in relevant) / weight,
        "receipt_completion_pct": sum(r["receipt_completion_pct"] * max(r["qty"], 1) for r in relevant) / weight,
    }


def _load_actuals(start, end, branches, groups):
    actual_end = min(getdate(end), getdate(frappe.utils.today()))
    if getdate(start) > actual_end:
        return {}
    rows = frappe.get_all(
        "Sales Forecast Daily",
        filters={
            "date": ["between", [str(start), str(actual_end)]],
            "branch": ["in", branches],
            "main_group": ["in", groups],
        },
        fields=[
            "date", "branch", "main_group", "retail_sales_value", "net_units",
            "store_open_flag", "transaction_count",
        ],
        limit_page_length=0,
    )
    return {
        (str(r.date), r.branch, r.main_group): r
        for r in rows
        if cint(r.store_open_flag) or cint(r.transaction_count)
    }


def preview(run_name):
    rows = frappe.db.sql(
        """
        select date,
               sum(forecast_sales) as forecast_sales,
               sum(forecast_sales_low) as forecast_low,
               sum(forecast_sales_high) as forecast_high,
               sum(actual_sales) as actual_sales
        from `tabSales Forecast Result`
        where forecast_run = %s
        group by date
        order by date asc
        """,
        (run_name,),
        as_dict=True,
    )
    return rows
