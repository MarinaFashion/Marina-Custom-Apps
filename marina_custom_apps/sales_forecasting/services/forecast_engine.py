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
    safe_field,
    settings,
)
from .data_mart import ensure_data_mart_coverage
from marina_custom_apps.marina_calendar.seasonal_matching import matching_basis, seasonal_weight


DORMANT_WARNING_DAYS = 14
WEEKDAY_PROFILE_DAYS = 365
MIN_WEEKDAY_OBSERVATIONS = 8
ASSORTMENT_FORWARD_HALF_LIFE_DAYS = 30


RESULT_FIELDS = [
    "name", "owner", "creation", "modified", "modified_by", "docstatus", "idx",
    "result_key", "forecast_run", "date", "branch", "main_group",
    "forecast_sales", "forecast_sales_low", "forecast_sales_high", "forecast_units",
    "forecast_asp", "confidence_pct", "has_actual_data", "actual_sales", "actual_units",
    "absolute_error", "signed_error", "absolute_pct_error", "analog_samples", "drivers",
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
        history_from = max(
            as_of - timedelta(days=lookback_years * 366),
            getdate(cfg.history_start_date),
        )
        history_to = as_of

        all_eligible_branches = get_branches(cfg)
        branches = all_eligible_branches
        if run.branch:
            branches = [b for b in branches if b.name == run.branch]
        groups = [run.main_group] if run.main_group else main_groups(cfg)
        if not branches or not groups:
            frappe.throw(_("No branches or groups match the forecast scope."))

        ensure_data_mart_coverage(
            history_from,
            history_to,
            branch_names=[branch.name for branch in branches],
            group_names=groups,
            commit=commit,
        )

        history = _load_history(
            history_from,
            history_to,
            groups,
            [branch.name for branch in branches],
        )
        pools = _build_pools(history)
        calendar = load_calendar(forecast_from, forecast_to, cfg)
        plan = (
            _resolve_plan(run, as_of, forecast_from, forecast_to)
            if cint(cfg.apply_buying_plan_adjustment)
            else None
        )
        plan_context = _plan_context(plan, as_of, cfg) if plan else {}

        # Keep weekday timing at the declared Company x Main Group scope even
        # when the Forecast Run itself is filtered to one Branch. Reuse the
        # already-loaded history for company-wide runs; only a branch-filtered
        # run needs one additional read-only history query.
        weekday_history = history
        if run.branch:
            weekday_history = _load_history(
                max(history_from, as_of - timedelta(days=WEEKDAY_PROFILE_DAYS - 1)),
                history_to,
                groups,
                [branch.name for branch in all_eligible_branches],
            )
        weekday_profile = _weekday_profile(weekday_history, as_of)

        assortment_context = _future_assortment_context(
            plan_context,
            as_of,
            forecast_from,
            forecast_to,
            groups,
            cfg,
        )

        actual_map = _load_actuals(forecast_from, forecast_to, [b.name for b in branches], groups)
        latest_context = _latest_context(history)
        branch_activity = _branch_activity_context(history, as_of)

        rows = []
        assortment_feature_cache = {}
        total_forecast_sales = total_forecast_units = 0.0
        total_actual_sales = total_actual_units = 0.0
        total_abs_error = total_signed_error = 0.0
        actual_rows = 0
        now = now_datetime()

        day = forecast_from
        while day <= forecast_to:
            cal = calendar.get(str(day), {})
            target = {
                "seasonal_matching_basis": matching_basis(cal.get("hijri_month"), cal.get("seasonal_matching_basis")),
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
                if target["seasonal_matching_basis"] == "Hijri" and not (
                    1 <= target["hijri_month"] <= 12 and 1 <= target["hijri_day"] <= 30
                ):
                    frappe.throw(_("Enter a valid Hijri day and month on Marina Calendar Date {0} before forecasting.").format(day))
                if branch.opening_date and getdate(branch.opening_date) > day:
                    continue
                activity = branch_activity.get(branch.name) or {}
                dormant_days = cint(activity.get("inactive_days"))
                last_sales_date = activity.get("last_sales_date")
                for group in groups:
                    cal_ctx = calendar_context(cal, branch, group, cfg.company)
                    target["hijri_day"] = cint(cal_ctx.get("hijri_day"))
                    target["hijri_month"] = cint(cal_ctx.get("hijri_month"))
                    target["event"] = cal_ctx.get("event") or ""
                    target["store_trading_status"] = cal_ctx.get("store_trading_status") or "No Change"
                    plan_features = _plan_features(plan_context, group, day)
                    assortment_key = (str(day), group)
                    if assortment_key not in assortment_feature_cache:
                        assortment_feature_cache[assortment_key] = _assortment_features(
                            assortment_context,
                            group,
                            day,
                            forecast_to,
                        )
                    # A copy is required because per-branch logic adds driver
                    # fields such as analog_target_new_styles_30d.
                    assortment_features = dict(
                        assortment_feature_cache[assortment_key]
                    )
                    recent = latest_context.get((branch.name, group), {})
                    recent_new_styles_30d = cint(recent.get("new_styles_30d"))
                    forward_style_pressure = assortment_features.get(
                        "assortment_target_style_pressure"
                    )
                    if (
                        cint(cfg.get("apply_known_assortment_matching"))
                        and assortment_features.get("assortment_available")
                    ):
                        # The historical analog feature is a 30-day new-style
                        # count. Use a 30-day-equivalent forward pressure score:
                        # every known display through Forecast To contributes,
                        # with exponential time decay rather than a hard cutoff.
                        target["new_styles_30d"] = flt(forward_style_pressure)
                        target["assortment_target_known"] = 1
                        assortment_features["assortment_signal_mode"] = "analog_matching"
                    else:
                        target["assortment_target_known"] = 0
                        target["new_styles_30d"] = (
                            plan_features.get("new_styles_30d")
                            if plan_features.get("new_styles_30d") is not None
                            else recent_new_styles_30d
                        )
                        assortment_features["assortment_signal_mode"] = "diagnostic_only"
                    assortment_features["analog_target_new_styles_30d"] = round(
                        flt(target["new_styles_30d"]), 2
                    )
                    assortment_features["recent_asof_new_styles_30d"] = recent_new_styles_30d
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
                        if dormant_days >= DORMANT_WARNING_DAYS:
                            pred["confidence"] = max(10, pred["confidence"] - 15)
                            pred["drivers"]["dormant_branch_warning"] = (
                                f"No sales transactions for {dormant_days} day(s) through {as_of}. "
                                "Verify Marina Calendar closure/reopening events."
                            )
                            pred["drivers"]["last_sales_date"] = str(last_sales_date) if last_sales_date else None
                            pred["drivers"]["inactive_days_as_of"] = dormant_days
                        if target["store_trading_status"] == "Partially Open":
                            pred["confidence"] = max(10, pred["confidence"] - 15)
                            pred["drivers"]["store_trading_status"] = "Partially Open"
                            pred["drivers"]["warning"] = "Partial operation; no automatic sales multiplier applied"
                    pred["drivers"]["forecast_store_type"] = (
                        branch.get("forecast_store_type") or "Regular Store"
                    )
                    weekday_index = flt(
                        (weekday_profile.get(group) or {}).get(day.strftime("%a")) or 1.0
                    )
                    pred["drivers"]["weekday_signal_mode"] = "diagnostic_only"
                    pred["drivers"]["seasonal_matching_basis"] = target["seasonal_matching_basis"]
                    pred["drivers"]["seasonal_matching_version"] = "v1"
                    if not target["hijri_month"]:
                        pred["drivers"]["seasonal_matching_warning"] = "Hijri month missing; Auto defaults to Gregorian unless explicitly overridden."
                    pred["drivers"]["weekday_profile_index"] = round(weekday_index, 4)
                    pred["drivers"]["weekday_profile_window_days"] = WEEKDAY_PROFILE_DAYS
                    pred["drivers"]["weekday_profile_scope"] = "Company x Main Group"
                    pred["drivers"].update(assortment_features)

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
                        pred["forecast_asp"], pred["confidence"], 1 if has_actual else 0,
                        actual_sales if has_actual else 0, actual_units if has_actual else 0,
                        abs_error if has_actual else 0, signed_error if has_actual else 0,
                        ape if has_actual else 0,
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

        # Weekday profile is diagnostic-only in v0.43.7. August validation
        # showed that applying a second post-model weekday multiplier slightly
        # worsened daily WAPE because exact weekday is already strongly weighted
        # in analog selection. Keep the learned index for analysis only.

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
            actual_result_count=actual_rows,
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
        # Never commit partially inserted Forecast Result rows or other uncommitted
        # forecast work when a run fails. Data Mart coverage is committed separately
        # before model execution when commit=True, so it remains available.
        frappe.db.rollback()
        _set_run(run.name, status="Failed", error_message=message[-4000:])
        frappe.db.commit()
        raise


def _weekday_profile(history, as_of):
    """Learn trailing Company x Main Group weekday demand indices as-of cutoff."""
    cutoff = getdate(as_of)
    start = cutoff - timedelta(days=WEEKDAY_PROFILE_DAYS - 1)

    daily = defaultdict(float)
    for row in history:
        day = getdate(row.date)
        if day < start or day > cutoff:
            continue
        if (row.store_trading_status or "No Change") == "Closed":
            continue
        daily[(row.main_group, day)] += flt(row.retail_sales_value)

    values = defaultdict(lambda: defaultdict(list))
    for (group, day), sales in daily.items():
        values[group][day.strftime("%a")].append(sales)

    profile = {}
    weekday_order = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
    for group, weekday_values in values.items():
        averages = {}
        valid = True
        for weekday in weekday_order:
            observations = weekday_values.get(weekday, [])
            if len(observations) < MIN_WEEKDAY_OBSERVATIONS:
                valid = False
                break
            averages[weekday] = sum(observations) / len(observations)

        if not valid:
            profile[group] = {weekday: 1.0 for weekday in weekday_order}
            continue

        baseline = sum(averages.values()) / len(weekday_order)
        if baseline <= 0:
            profile[group] = {weekday: 1.0 for weekday in weekday_order}
            continue
        profile[group] = {
            weekday: averages[weekday] / baseline
            for weekday in weekday_order
        }

    return profile


def _apply_weekday_profile(rows, profile):
    """Redistribute daily timing without changing Branch x Group period sales."""
    if not rows or not profile:
        return

    idx = {fieldname: i for i, fieldname in enumerate(RESULT_FIELDS)}
    buckets = defaultdict(list)
    for row in rows:
        buckets[(row[idx["branch"]], row[idx["main_group"]])].append(row)

    for (_, group), bucket in buckets.items():
        factors = profile.get(group)
        if not factors:
            continue

        base_total = sum(flt(row[idx["forecast_sales"]]) for row in bucket)
        weighted_total = 0.0
        for row in bucket:
            weekday = getdate(row[idx["date"]]).strftime("%a")
            weighted_total += (
                flt(row[idx["forecast_sales"]])
                * flt(factors.get(weekday) or 1.0)
            )

        if base_total <= 0 or weighted_total <= 0:
            continue

        normalizer = base_total / weighted_total
        for row in bucket:
            weekday = getdate(row[idx["date"]]).strftime("%a")
            weekday_index = flt(factors.get(weekday) or 1.0)
            adjustment = weekday_index * normalizer

            for fieldname in (
                "forecast_sales",
                "forecast_sales_low",
                "forecast_sales_high",
                "forecast_units",
            ):
                row[idx[fieldname]] = flt(row[idx[fieldname]]) * adjustment

            drivers = frappe.parse_json(row[idx["drivers"]]) or {}
            drivers["weekday_profile_index"] = round(weekday_index, 4)
            drivers["weekday_profile_normalizer"] = round(normalizer, 4)
            drivers["weekday_adjustment_factor"] = round(adjustment, 4)
            drivers["weekday_profile_window_days"] = WEEKDAY_PROFILE_DAYS
            drivers["weekday_profile_scope"] = "Company x Main Group"
            row[idx["drivers"]] = json.dumps(drivers, ensure_ascii=False)


def _result_metrics(rows):
    """Recompute totals and actual errors after post-model timing redistribution."""
    idx = {fieldname: i for i, fieldname in enumerate(RESULT_FIELDS)}
    metrics = {
        "forecast_sales": 0.0,
        "forecast_units": 0.0,
        "actual_sales": 0.0,
        "actual_units": 0.0,
        "absolute_error": 0.0,
        "signed_error": 0.0,
        "actual_rows": 0,
    }

    for row in rows:
        forecast_sales = flt(row[idx["forecast_sales"]])
        metrics["forecast_sales"] += forecast_sales
        metrics["forecast_units"] += flt(row[idx["forecast_units"]])

        if not cint(row[idx["has_actual_data"]]):
            continue

        actual_sales = flt(row[idx["actual_sales"]])
        actual_units = flt(row[idx["actual_units"]])
        absolute_error = abs(forecast_sales - actual_sales)
        signed_error = forecast_sales - actual_sales
        ape = (
            absolute_error / abs(actual_sales) * 100
            if actual_sales
            else 0
        )

        row[idx["absolute_error"]] = absolute_error
        row[idx["signed_error"]] = signed_error
        row[idx["absolute_pct_error"]] = ape

        metrics["actual_sales"] += actual_sales
        metrics["actual_units"] += actual_units
        metrics["absolute_error"] += absolute_error
        metrics["signed_error"] += signed_error
        metrics["actual_rows"] += 1

    return metrics


def _future_assortment_context(plan_context, as_of, forecast_from, forecast_to, groups, cfg):
    """Return leakage-conscious future assortment context for diagnostics.

    Approved Buying Plan is authoritative when available. Otherwise, use only
    Item/style records that were already created by the forecast as-of date.
    Item-derived features remain diagnostic-only because field edits after as-of
    cannot be reconstructed from current master data.
    """
    if plan_context:
        result = defaultdict(list)
        for group, rows in plan_context.items():
            for row in rows:
                copied = dict(row)
                copied["source"] = "Buying Plan"
                result[group].append(copied)
        return result

    display_field = safe_field(cfg.item_display_date_field, "display_date")
    group_field = safe_field(cfg.item_main_group_field, "custom_item_main_group")
    placeholders = ",".join(["%s"] * len(groups))
    start = getdate(forecast_from) - timedelta(days=29)
    end = getdate(forecast_to)

    sql = f"""
        select
            coalesce(nullif(i.variant_of, ''), i.name) as style,
            coalesce(
                nullif(cast(i.`{group_field}` as char), ''),
                nullif(cast(template.`{group_field}` as char), '')
            ) as main_group,
            coalesce(i.`{display_field}`, template.`{display_field}`) as display_date
        from `tabItem` i
        left join `tabItem` template on template.name = i.variant_of
        where i.disabled = 0
          and date(i.creation) <= %s
          and coalesce(i.`{display_field}`, template.`{display_field}`) between %s and %s
          and coalesce(
                nullif(cast(i.`{group_field}` as char), ''),
                nullif(cast(template.`{group_field}` as char), '')
              ) in ({placeholders})
        group by style, main_group, display_date
    """
    data = frappe.db.sql(
        sql,
        [str(as_of), str(start), str(end), *groups],
        as_dict=True,
    )

    result = defaultdict(list)
    seen = set()
    for row in data:
        if not row.display_date or not row.main_group:
            continue
        key = (row.style, row.main_group, str(row.display_date))
        if key in seen:
            continue
        seen.add(key)
        result[row.main_group].append(
            {
                "display_date": getdate(row.display_date),
                "styles": 1.0,
                "qty": 0.0,
                "selling": 0.0,
                "source": "Item master (created by as-of; diagnostic only)",
            }
        )
    return result


def _assortment_features(context, group, day, forecast_to):
    """Build a forward-looking assortment signal over the requested horizon.

    Every display already known by the forecast cutoff can contribute when its
    Display Date is still relevant to the requested forecast. There is no
    30-day future cutoff.

    To remain comparable with the historical ``new_styles_30d`` analog feature,
    the target combines:
    - styles displayed in the rolling 30 days through the forecast day; and
    - all still-future styles through Forecast To, exponentially time-decayed.

    On the display date a style therefore moves from future pressure into the
    recent 30-day count instead of disappearing from the signal.
    """
    horizon_end = getdate(forecast_to)
    recent_start = day - timedelta(days=29)
    all_rows = [
        row
        for group_rows in context.values()
        for row in group_rows
    ]
    rows = context.get(group, [])
    available = bool(all_rows)

    def is_recent(row):
        display_date = getdate(row["display_date"])
        return recent_start <= display_date <= day

    def is_future(row):
        display_date = getdate(row["display_date"])
        return day < display_date <= horizon_end

    def decay(row):
        days_ahead = max((getdate(row["display_date"]) - day).days, 0)
        return 0.5 ** (days_ahead / ASSORTMENT_FORWARD_HALF_LIFE_DAYS)

    group_recent = [row for row in rows if is_recent(row)]
    group_future = [row for row in rows if is_future(row)]
    all_future = [row for row in all_rows if is_future(row)]

    recent_styles = sum(flt(row.get("styles")) for row in group_recent)
    weighted_future_styles = sum(
        flt(row.get("styles")) * decay(row) for row in group_future
    )
    weighted_all_future_styles = sum(
        flt(row.get("styles")) * decay(row) for row in all_future
    )
    raw_future_styles = sum(flt(row.get("styles")) for row in group_future)
    raw_all_future_styles = sum(flt(row.get("styles")) for row in all_future)

    weighted_qty = sum(flt(row.get("qty")) * decay(row) for row in group_future)
    weighted_all_qty = sum(flt(row.get("qty")) * decay(row) for row in all_future)
    weighted_value = sum(flt(row.get("selling")) * decay(row) for row in group_future)
    weighted_all_value = sum(flt(row.get("selling")) * decay(row) for row in all_future)

    target_style_pressure = recent_styles + weighted_future_styles

    display_dates = sorted(
        getdate(row["display_date"])
        for row in group_future
        if row.get("display_date")
    )
    next_display = display_dates[0] if display_dates else None

    source = None
    if rows:
        source = rows[0].get("source")
    elif all_rows:
        source = all_rows[0].get("source")

    result = {
        "assortment_signal_mode": "diagnostic_only",
        "assortment_source": source,
        "assortment_available": 1 if available else 0,
        "assortment_horizon_end": str(horizon_end),
        "assortment_decay_half_life_days": ASSORTMENT_FORWARD_HALF_LIFE_DAYS,
        "recent_styles_30d": round(recent_styles, 2),
        "future_styles_in_forecast": round(raw_future_styles, 2),
        "weighted_future_styles_in_forecast": round(weighted_future_styles, 4),
        "assortment_target_style_pressure": round(target_style_pressure, 4),
        "future_style_share_in_forecast_pct": (
            round(raw_future_styles / raw_all_future_styles * 100, 2)
            if raw_all_future_styles
            else 0.0 if available else None
        ),
        "weighted_future_style_share_pct": (
            round(
                weighted_future_styles / weighted_all_future_styles * 100,
                2,
            )
            if weighted_all_future_styles
            else 0.0 if available else None
        ),
        "weighted_planned_qty_share_pct": (
            round(weighted_qty / weighted_all_qty * 100, 2)
            if weighted_all_qty
            else None
        ),
        "weighted_planned_value_share_pct": (
            round(weighted_value / weighted_all_value * 100, 2)
            if weighted_all_value
            else None
        ),
        "next_display_date": str(next_display) if next_display else None,
        "days_to_next_display": (
            max((next_display - day).days, 0)
            if next_display
            else None
        ),
    }
    if source and source.startswith("Item master"):
        result["assortment_backtest_caution"] = (
            "Item master was created by the forecast cutoff, but later edits to "
            "Display Date are not historically versioned. Prefer Buying Plan "
            "versions for strict historical backtests."
        )
    return result

def _validate_run(run):
    if run.status == "Completed":
        frappe.throw(
            _("Completed Forecast Runs are immutable. Create a new Forecast Run instead.")
        )

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


def _load_history(start, end, groups, branches):
    filters = {
        "date": ["between", [str(start), str(end)]],
        "main_group": ["in", groups],
    }
    if branches:
        filters["branch"] = ["in", branches]
    return frappe.get_all(
        "Sales Forecast Daily",
        filters=filters,
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
        basis = target["seasonal_matching_basis"]
        if basis == "Hijri":
            w *= seasonal_weight(basis, cint(target.get("hijri_month")),
                                 cint(target.get("hijri_day")), cint(row.hijri_month), cint(row.hijri_day))
        else:
            historical_date = getdate(row.date)
            w *= seasonal_weight(basis, target_date.month, target_date.day,
                                 historical_date.month, historical_date.day)
        if target["event"] and row.event == target["event"]:
            w *= 1.6
        elif not target["event"] and not row.event:
            w *= 1.05

        if cint(target.get("assortment_target_known")):
            diff = abs(flt(row.new_styles_30d) - target_new)
            w *= 0.65 + 0.35 * math.exp(-diff / max(target_new, 5))
        elif target_new > 0:
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
            "seasonal_matching_basis": target["seasonal_matching_basis"],
            "seasonal_matching_version": "v1",
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


def _branch_activity_context(history, as_of):
    latest = {}
    for row in history:
        if cint(row.transaction_count) <= 0 and flt(row.retail_sales_value) == 0:
            continue
        day = getdate(row.date)
        if day > getdate(as_of):
            continue
        previous = latest.get(row.branch)
        if previous is None or day > previous:
            latest[row.branch] = day

    result = {}
    for branch, last_day in latest.items():
        result[branch] = {
            "last_sales_date": last_day,
            "inactive_days": max((getdate(as_of) - last_day).days, 0),
        }
    return result


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

    Execution readiness follows the same Year + Season + Main Group grain as the
    operational Buying Plan refresh. Collection, Drop and Display Date remain
    timing dimensions, but they do not block recognition of seasonal supply.
    """
    context = defaultdict(list)
    if not plan:
        return context

    grouped = defaultdict(lambda: {"planned_qty": 0.0, "rows": []})
    for row in plan.items:
        group = (row.main_group or "").strip()
        grouped[group]["planned_qty"] += flt(row.planned_total_qty)
        grouped[group]["rows"].append(row)

    for group, bucket in grouped.items():
        execution = _execution_as_of(plan, group, as_of, cfg)
        group_qty = flt(bucket["planned_qty"])
        po_pct = min(100, execution["po_qty"] / group_qty * 100) if group_qty else 0
        receipt_pct = min(100, execution["received_qty"] / group_qty * 100) if group_qty else 0

        for row in bucket["rows"]:
            context[group].append({
                "display_date": getdate(row.display_date),
                "styles": flt(row.planned_styles),
                "qty": flt(row.planned_total_qty),
                "selling": flt(row.planned_selling_value),
                "po_completion_pct": po_pct,
                "receipt_completion_pct": receipt_pct,
            })
    return context


def _execution_as_of(plan, main_group, as_of, cfg):
    from .common import safe_field

    item_year = safe_field(cfg.item_year_field, "item_year")
    item_season = safe_field(cfg.item_season_field, "season")
    item_group = safe_field(cfg.item_main_group_field, "custom_item_main_group")

    def resolved(fieldname):
        return (
            f"coalesce("
            f"nullif(cast(i.`{fieldname}` as char), ''), "
            f"nullif(cast(template.`{fieldname}` as char), '')"
            f")"
        )

    classification = [str(plan.plan_year), plan.season, main_group]
    where = f"""
        {resolved(item_year)} = %s
        and {resolved(item_season)} = %s
        and {resolved(item_group)} = %s
    """

    po_qty = frappe.db.sql(
        f"""
        select coalesce(sum(poi.qty), 0)
        from `tabPurchase Order Item` poi
        inner join `tabPurchase Order` po on po.name = poi.parent
        inner join `tabItem` i on i.name = poi.item_code
        left join `tabItem` template on template.name = i.variant_of
        where po.docstatus = 1
          and po.company = %s
          and po.transaction_date <= %s
          and date(po.creation) <= %s
          and {where}
        """,
        [plan.company, str(as_of), str(as_of), *classification],
    )[0][0] or 0

    received_qty = frappe.db.sql(
        f"""
        select coalesce(sum(pri.qty), 0)
        from `tabPurchase Receipt Item` pri
        inner join `tabPurchase Receipt` pr on pr.name = pri.parent
        inner join `tabItem` i on i.name = pri.item_code
        left join `tabItem` template on template.name = i.variant_of
        where pr.docstatus = 1
          and pr.company = %s
          and pr.posting_date <= %s
          and date(pr.creation) <= %s
          and {where}
        """,
        [plan.company, str(as_of), str(as_of), *classification],
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
    actual_end = min(getdate(end), getdate(add_days(frappe.utils.today(), -1)))
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
            "store_open_flag", "transaction_count", "store_trading_status",
        ],
        limit_page_length=0,
    )
    # The caller only requests completed dates. Presence of an eligible
    # Date x Branch x Main Group Data Mart row is therefore authoritative
    # actual coverage, including legitimate zero-sales days.
    return {
        (str(r.date), r.branch, r.main_group): r
        for r in rows
    }


def refresh_actuals(run_name, *, commit=True):
    """Refresh realized actuals without changing the frozen forecast prediction."""
    run = frappe.get_doc("Sales Forecast Run", run_name)
    if run.status != "Completed":
        frappe.throw(_("Actuals can be refreshed only for a Completed Forecast Run."))

    start = getdate(run.forecast_from)
    actual_end = min(getdate(run.forecast_to), getdate(add_days(frappe.utils.today(), -1)))
    if start > actual_end:
        return {"run": run.name, "actual_through": None, "actual_rows": 0, "result_rows": cint(run.result_count)}

    eligible = {
        branch.name
        for branch in get_branches(settings(), include_disabled_stores=True)
    }
    result_branches = set(frappe.get_all(
        "Sales Forecast Result",
        filters={"forecast_run": run.name},
        pluck="branch",
        limit_page_length=0,
    ))
    branches = sorted(eligible.intersection(result_branches))
    groups = sorted(set(frappe.get_all(
        "Sales Forecast Result",
        filters={"forecast_run": run.name},
        pluck="main_group",
        limit_page_length=0,
    )))
    if not branches or not groups:
        frappe.throw(_("No eligible store results were found for this Forecast Run."))

    # Preserve Sales Forecast Daily immutability. Refresh Actuals creates only
    # missing realized rows. Corrected historical transactions require the
    # explicit System Manager Data Mart Maintenance -> Delete & Rebuild action.
    ensure_data_mart_coverage(
        start,
        actual_end,
        branch_names=branches,
        group_names=groups,
        commit=False,
        include_disabled_stores=True,
    )
    actual_map = _load_actuals(start, actual_end, branches, groups)
    results = frappe.get_all(
        "Sales Forecast Result",
        filters={"forecast_run": run.name},
        fields=["name", "date", "branch", "main_group", "forecast_sales"],
        order_by="date asc, branch asc, main_group asc",
        limit_page_length=0,
    )

    total_actual_sales = total_actual_units = 0.0
    total_abs_error = total_signed_error = 0.0
    actual_rows = 0
    for row in results:
        if row.branch not in eligible or getdate(row.date) > actual_end:
            continue
        actual = actual_map.get((str(row.date), row.branch, row.main_group))
        has_actual = actual is not None
        actual_sales = flt(actual.get("retail_sales_value")) if has_actual else 0
        actual_units = flt(actual.get("net_units")) if has_actual else 0
        abs_error = abs(flt(row.forecast_sales) - actual_sales) if has_actual else 0
        signed_error = flt(row.forecast_sales) - actual_sales if has_actual else 0
        ape = abs_error / abs(actual_sales) * 100 if has_actual and actual_sales else 0

        frappe.db.set_value("Sales Forecast Result", row.name, {
            "has_actual_data": 1 if has_actual else 0,
            "actual_sales": actual_sales if has_actual else 0,
            "actual_units": actual_units if has_actual else 0,
            "absolute_error": abs_error if has_actual else 0,
            "signed_error": signed_error if has_actual else 0,
            "absolute_pct_error": ape if has_actual else 0,
        }, update_modified=False)

        if has_actual:
            total_actual_sales += actual_sales
            total_actual_units += actual_units
            total_abs_error += abs_error
            total_signed_error += signed_error
            actual_rows += 1

    wape = total_abs_error / abs(total_actual_sales) * 100 if total_actual_sales else 0
    bias = total_signed_error / abs(total_actual_sales) * 100 if total_actual_sales else 0
    mae = total_abs_error / actual_rows if actual_rows else 0
    accuracy = max(0, 100 - wape) if actual_rows else 0

    _set_run(
        run.name,
        actual_sales=total_actual_sales if actual_rows else 0,
        actual_units=total_actual_units if actual_rows else 0,
        wape=wape if actual_rows else 0,
        accuracy_pct=accuracy if actual_rows else 0,
        bias_pct=bias if actual_rows else 0,
        mae=mae if actual_rows else 0,
        actual_result_count=actual_rows,
    )
    if commit:
        frappe.db.commit()
    return {
        "run": run.name,
        "actual_through": str(actual_end),
        "actual_rows": actual_rows,
        "result_rows": len(results),
        "wape": wape if actual_rows else None,
        "bias": bias if actual_rows else None,
    }


def preview(run_name):
    rows = frappe.db.sql(
        """
        select date,
               sum(forecast_sales) as forecast_sales,
               sum(forecast_sales_low) as forecast_low,
               sum(forecast_sales_high) as forecast_high,
               case
                   when count(*) > 0 and sum(has_actual_data) = count(*)
                   then sum(actual_sales)
                   else null
               end as actual_sales
        from `tabSales Forecast Result`
        where forecast_run = %s
        group by date
        order by date asc
        """,
        (run_name,),
        as_dict=True,
    )
    return rows
