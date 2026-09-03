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
Supports Future and Backtest runs. The MVP engine is `Marina Analog Ensemble v1`: weighted historical analogs with recency, weekday/weekend, Hijri position, salary phase, events, assortment newness, markdown, stockout awareness, branch/cluster/city fallback, store-space scaling, trend and Buying Plan price/supply context.

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
