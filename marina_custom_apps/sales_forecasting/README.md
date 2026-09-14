# Marina Sales Forecasting

ERPNext/Frappe v15 forecasting module for Marina Fashion. It turns operational ERP data into a permanent forecasting data mart, preserves Buying Plan versions, runs repeatable future forecasts/backtests, and measures forecast error automatically.

## Source-of-truth mapping

- Sales: submitted `Sales Invoice` / `Sales Invoice Item`; returns are already negative.
- Retail sales: `Sales Invoice Item.amount` (incl. VAT in Marina's configuration).
- Net revenue: `Sales Invoice Item.net_amount` (ex. VAT).
- Store master: `Branch` with Marina's custom links to Warehouse, POS Profile, Cost Center, opening date, city, cluster and store space.
- Product hierarchy: Item year/season/collection/drop/main group/subgroup, `variant_of` as Style, Size from variants, `display_date` for product newness.
- Historical inventory: `Stock Ledger Entry.qty_after_transaction` reconstructed by Store x SKU x Date.
- Pricing/markdown: latest valid `Item Price` in `Standard Selling`; first valid selling price is launch price.
- Store operating time: union of valid POS Closing Shift intervals per Branch/POS Profile/day; overlapping cashier shifts are not double-counted.
- Calendar: configurable existing Date/Hijri/Event DocType, auto-detected from the confirmed fields.
- Salary cycle: 25-26 Pre-Salary, 27-end + 1-3 Salary Peak, 4-9 Decline, 10-24 Normal.
- Future commercial intent: versioned `Forecast Buying Plan`.
- Buying execution: submitted Purchase Orders and Purchase Receipts for matching merchandise; supplier is not part of forecast/readiness classification.

## Main documents

### Forecast Buying Plan
Paste the Buying Plan directly from Excel. Stored inputs are Year, Season, Collection, Drop, Display Date, Main Group, Planned Styles, Planned Qty, Planned Cost and Planned Selling Value. Averages, ex-VAT selling value, gross profit and planned margin are calculated automatically. Submitted versions are immutable; new revisions preserve what was known at each point in time.

### Sales Forecast Daily
Read-only data mart at Date x Branch x Main Group. It stores demand, operating status, assortment/newness, inventory availability, markdown, Hijri/event features and salary phase. Scheduled refresh updates recent history each night.

### Sales Forecast Run
Supports Future and Backtest runs. The MVP engine is `Marina Analog Ensemble v1`: weighted historical analogs with recency, weekday/weekend, Hijri position, salary phase, events, assortment newness, markdown, stockout awareness, branch/cluster/city fallback, store-space scaling, trend and Buying Plan price/supply context. Hijri-driven periods use observations from the corresponding Hijri month as their primary pool; broader history is used only when that seasonal pool is unavailable.

### Sales Forecast Result
Daily Branch x Main Group forecast, interval, confidence, actuals (when available), errors and diagnostic driver JSON.

### Forecast Accuracy Analysis
Interactive Script Report for Forecast vs Actual, WAPE-derived accuracy, bias, confidence and daily trend chart.

## Backtest integrity

A backtest uses only information available through the Run's `as_of_date`. Buying Plan version is constrained by `effective_from`, and PO/receipt completion is recomputed using documents created/posted by the as-of date instead of today's cumulative progress.

## Recommended first calibration

1. Build the data mart from 2023-01-01 through yesterday.
2. Create/import approved Buying Plans for periods where the historic plans are available.
3. Run several rolling backtests (for example 30/60/90-day horizons).
4. Compare WAPE and Bias by season, branch and group.
5. Calibrate model weights/ranges only after the backtest evidence is visible.

This v1 intentionally has no external ML dependency so it runs inside the current Frappe v15 app. The data mart/model-version design is ready for a later CatBoost/LightGBM model if evidence shows that it materially improves rolling backtests.

## Readiness matching (v0.43.3)

ERP Buying Readiness is aggregated at `Year + Season + Main Group`. Collection, Drop and Display Date stay in the Buying Plan because they are important for display timing and forecasting, but they no longer block merchandise-readiness recognition. Purchase Orders are supplier-neutral, and Received Qty is read directly from submitted Purchase Receipts. Variant classification falls back to the Item Template when a mapped value is blank on the variant.

Sales Forecast Settings field mappings use dynamic autocomplete dropdowns populated from the actual installed Branch and Item fields, with server-side validation to prevent invalid field names.

## v0.43.4 operational hardening

- Forecast Runs ensure their required historical Data Mart coverage automatically and insert only missing `Date + Branch + Main Group` keys. Existing Daily records are not recreated or updated.
- The automatic daily Data Mart rebuild scheduler was removed.
- System Managers can use **Sales Forecast Daily -> Data Mart Maintenance** to delete or delete-and-rebuild a corrected date range, optionally scoped by Branch/Main Group.
- Forecast Result rows distinguish unavailable actuals using `Has Actual Data`, avoiding null-insert failures for future forecasts/backtests without loaded actuals.
- Forecast workspace KPI methods are whitelisted with underlying DocType permission checks and correct Number Card permission context.
- Buying Plan overall assortment/PO/receipt completion percentages cap each Main Group contribution so over-completion in one group cannot offset a shortage in another.
- Sales Forecast Settings use two-column desktop sections, validate operational ranges, and repair only missing/invalid legacy defaults during migration.
- Completed Forecast Runs are immutable audit records: they cannot be edited, rerun, or deleted; corrected inputs must be tested with a new run.
## v0.43.5 forecast scope, audit and analysis hardening

- Forecast eligibility now requires the Branch-linked Warehouse to be an active, non-group selling store (`custom_is_store = 1`, `disabled = 0`, `is_group = 0`).
- Historical analog pools use the same eligible Branch universe so office/DC/non-store rows cannot contaminate fallback pools.
- Critical negative Operational calendar events warn when Store Trading Status remains `No Change`.
- Dormant branches are flagged in model drivers and receive a confidence penalty without changing forecast amount.
- Completed Forecast Runs can refresh realized actuals without changing frozen forecast predictions or silently rebuilding existing historical Data Mart rows.
- `Has Actual Data` is authoritative for all accuracy calculations; completed generated Data Mart rows count as realized actual coverage even when sales are zero.
- Forecast Accuracy Analysis supports Detail, Daily, Branch, Main Group and Branch x Main Group levels.
- Forecast by Store and Main Group shows collapsed Store totals with expandable Daily rows and optional Units.
## v0.43.6 selling-location, weekday and assortment foundation

- Branch now has an explicit Sales Forecasting classification: Regular Store, Outlet, Online or Other, plus an Include in Sales Forecast flag.
- Existing active Warehouse selling stores are initialized as Regular Store + Included during migration; later user classifications are never overwritten.
- Outlet/Online locations can participate in forecasting without changing Warehouse.custom_is_store, protecting Stock Allocation and other warehouse processes.
- A trailing 365-day Company x Main Group weekday curve is learned strictly through the run as-of date.
- Weekday factors redistribute daily timing inside each Branch x Main Group while preserving that Branch x Group period forecast sales total.
- Future assortment pressure (7/14/30-day style counts and 30-day mix; Buying Plan quantity/value shares when available) is recorded in model drivers in diagnostic-only mode and does not yet alter forecast amount.
- Refresh Actuals creates only missing Sales Forecast Daily coverage; it no longer silently replaces historical Data Mart rows.
## v0.43.7 assortment-aware analog matching

- The 365-day weekday profile is retained in model drivers for diagnostics only. It no longer applies a second post-model multiplier because August validation showed a slight deterioration in daily WAPE and the analog model already weights exact weekday strongly.
- A new setting, `Use Known Future Assortment in Analog Matching`, is enabled by default.
- The model reconstructs the rolling 30-day new-style count for each future Main Group using display dates known by the forecast cutoff.
- That known assortment count changes analog similarity only; there is no direct Bottoms/Uppers/Dresses sales multiplier.
- Future style, planned quantity and planned value shares remain visible in model drivers for analysis.
- Item-master fallback is restricted to Item records created by the as-of date and is flagged in drivers because later Display Date edits are not historically versioned.
## v0.43.8 forecast-period assortment horizon

- Known future assortment is no longer limited to a fixed 30-day future window.
- Every display date already known by the forecast cutoff can contribute when it falls inside the requested Forecast From/To period.
- A 30-day **half-life**, not a cutoff, applies time decay so nearer launches influence the current forecast day more strongly while distant launches still contribute.
- Drivers expose remaining styles, weighted style pressure, style share, planned quantity/value shares, next display date and days to next display.
- Forward assortment remains an analog-matching signal only; no direct Main Group multiplier is applied.
- Forward assortment uses a gentler analog-weight penalty than legacy recent-assortment matching to reduce distortion of branch-level demand allocation.
