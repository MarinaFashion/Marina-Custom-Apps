# Marina Custom Apps

**Marina Custom Apps** (`marina_custom_apps`) is Marina Trading Company's consolidated Frappe / ERPNext application for fashion retail operations. It extends standard ERPNext rather than replacing its accounting, purchasing, stock-ledger, and permission foundations.

The application covers stock logistics, inventory audit and counting, buying and receiving, forecasting, operational calendars and procedures, POS/bank reconciliation, permission administration, and design-to-production coordination.

> **Documentation scope:** This README describes functionality present in the repository's `main` branch. It is not a claim that every feature has been enabled, migrated, configured, or user-accepted on every site. Review permissions, settings, migration output, and demo UAT before production use.

## Platform and application structure

| Item | Repository definition |
| --- | --- |
| Python package | `marina_custom_apps` |
| Package release | `0.53.25` (from `pyproject.toml`) |
| Framework | Frappe 15.x |
| ERP | ERPNext 15.x |
| Deployment | Frappe / ERPNext bench; Marina uses Frappe Cloud |
| Publisher | Marina Trading Company |
| Source of truth | GitHub `main`; installed-site behavior depends on deployed commit and site configuration |

`pyproject.toml` constrains Frappe and ERPNext to `>=15,<16`. The `hooks.py` version string is not currently aligned with `pyproject.toml`; use the package metadata and deployed commit for release identification, not the hooks string alone.

The registered Frappe modules are:

| Business area | Registered module | Core purpose |
| --- | --- | --- |
| Navigation / shared features | Marina Custom Apps | Shared module navigation, ERPNext form enhancements, purchasing reports |
| Stock movement | Stock Transfer Control | Physical/transit routing and stock movement validation |
| Stock verification | Stock Transfer Audit | Sent/received discrepancy monitoring and corrective actions |
| Initial distribution | DC Dispatch | First distribution of newly received merchandise from DC to stores |
| Reallocation | Stock Auto Allocation | Redistribute existing stock among DC and stores |
| Inventory accuracy | Cycle Count | Store counting, coverage tracking and variances |
| Demand planning | Sales Forecasting | Historical data mart, buying plans, forecasts and accuracy analysis |
| Commercial calendar | Marina Calendar | Hijri/Gregorian dates, events, closures and forecast features |
| Controlled procedures | SOP Management | SOP authoring, approvals, publishing, library and version history |
| Administration | Permission Manager | Bulk access administration and access reporting |
| Payments / finance | POS Reconciliation | POS–terminal–bank statement matching, exceptions and accounting controls |
| Product development | Marina Design Management | Mood boards, designs, milestone custody, production follow-up, documents and discussions |

Specialist workspaces are separately permissioned. The Marina Custom Apps umbrella is a shared application identity, not a grant to all operational modules. Some historical documents describe earlier workspace or module configurations; current workspace files and installed-site permissions take precedence.

---

## 1. Stock Transfer Control

Controls warehouse movements and enforces safe logistics execution:

- Controlled **Send Stock**, **Receive Stock**, and **Transfer Between** processes, including physical ↔ transit warehouse routing.
- Material Request → Stock Entry execution with protection against changing the approved transfer route.
- Server-side validation of warehouse routes, authorization, and stock-entry lifecycle events.
- End Transit / physical receipt handling; receiving differences are tracked without fabricating unintended Stock Ledger Entries.
- English/Arabic warehouse search using `Warehouse.custom_warehouse_name_arabic`.
- Common execution infrastructure for DC Dispatch, Stock Auto Allocation and Stock Transfer Audit.

**Typical flow:** approved Material Request → Send Stock → transit → Receive Stock → audit/corrective transfer.

## 2. Stock Transfer Audit

Compares sent stock with actual receiving evidence and provides discrepancy follow-up:

- Date-scoped Stock Transfer Audit Runs and item-level audit records.
- Shortage, excess and unexpected-item visibility.
- Controlled corrective operations such as **Return Discrepancy to Source** and **Send Discrepancy to Target**.
- Transfer status integration and original Stock Entry traceability.
- Operational reports: **Open Transit Aging**, **Pending Audit Variance**, **Variance Summary**, **Receiver Performance** and **Ignore Analysis**.
- Configurable controls, KPIs and daily audit/transfer alerts.

## 3. DC Dispatch

Plans the **first allocation of new receipts** from the distribution center:

- Merchandise filters by Year, Season, Collection, Drop, display date, merchandise grouping and hierarchy.
- Demand-oriented allocation from historical branch sales and store segmentation.
- Store priorities, minimum display quantities, min/max limits and dispatch allocation percentages.
- Preservation of style/size variant distribution.
- Allocation proposals, review/approval and Material Request generation.
- Stock Transfer Control performs the subsequent physical movement.

## 4. Stock Auto Allocation

Plans the **reallocation of stock already in the network**:

- DC → store and store → store proposals.
- Historical sales, velocity, days of cover, source-store stock protection and selling potential.
- Size completeness, minimum display protection, immature-sales-history handling and new-release grace periods.
- Store distance, donor selection, transfer thresholds and city-level shipment consolidation.
- Transfer Shipment Batches for qualifying routes, with approved Material Requests passed to Stock Transfer Control.

Planning results do not directly replace ERPNext's stock-ledger authority.

## 5. Cycle Count

Provides store inventory counting and stock accuracy controls:

- **Cycle Count Plan** and **Store Cycle Count** documents with line-level count items.
- Store/style-oriented count planning and coverage history by variant.
- Count coverage, variance and pending count reporting.
- Permission-controlled store counting and linkage to submitted/cancelled Stock Reconciliations.
- KPI and coverage services for monitoring how much of the assortment has been verified.

Relevant reports include **Cycle Count Coverage**, **Cycle Count Variance** and **Pending Cycle Counts**.

## 6. Sales Forecasting

ERPNext-native forecasting and buying-readiness analysis, built around reproducible historical data:

- **Forecast Buying Plan** with Excel paste, versioned planning inputs and immutable submitted versions.
- **Sales Forecast Daily** data mart at Date × Branch × Main Group, incorporating sales, stock availability, newness, pricing/markdown, store operations, salary periods and calendar signals.
- **Sales Forecast Run** for future projections and backtests using Marina's analog-ensemble model.
- Hijri/Gregorian matching, event/closure handling, weekday/seasonality signals, store/cluster fallback and known future assortment in analog matching.
- Forecast result details with confidence intervals, drivers, actuals when available and errors.
- Forecast accuracy and bias/WAPE analysis, plus **Forecast by Store and Main Group** reporting.
- Historical `as_of_date` controls so backtesting does not use information learned after the evaluation cutoff.
- Controlled data-mart maintenance and refresh of realized actuals; completed runs remain historical audit records.

See [Sales Forecasting documentation](marina_custom_apps/sales_forecasting/README.md) for assumptions, data mappings, calibration and model evolution.

## 7. Marina Calendar

Maintains the commercial and operating calendar used by reporting and forecasting:

- **Marina Calendar Date**: Gregorian date, Hijri attributes and synchronized event listing.
- **Marina Calendar Event**: date-range events scoped to company, city, branch and optionally Main Group.
- Frappe Month/Week/Day calendar views and event filters.
- **Closed** / **Partially Open** trading status and forecast-relevant event attributes.
- Events are the authoritative source; date-level child rows are refreshed automatically.
- Calendar Date can be maintained through standard import and provides a shortcut to create an event for that date.

See [Marina Calendar documentation](marina_custom_apps/marina_calendar/README.md).

## 8. SOP Management

Controlled creation and publication of internal policies and procedures:

- **SOP Type**, **SOP Document**, **SOP Version** and section content.
- Draft → Under Review → Approved → Published lifecycle, with archive and superseding/version controls.
- English, Arabic and bilingual content; rich text or sanitized advanced HTML.
- SOP Library organized by type, department and document number.
- Audience/visibility restrictions by designation, department, employee or user.
- Controlled document preview, print/PDF format, branding, metadata and revision history.
- SOP Manager, Editor and Viewer roles.

The module's documented Phase 1 scope does **not** include employee acknowledgements, training assignments or scheduled review reminders. See [SOP Management documentation](marina_custom_apps/sop_management/README.md).

## 9. Permission Manager and ERPNext shared enhancements

Central administration of user access:

- Role ↔ User management, User Permissions, module access, workspace access, Page and Report permissions.
- Administrative bulk assignment and explicit conversion of formerly open Page/Report access into authorized role lists.
- Permission reports and module/workspace access summaries.
- Direct user-role changes remain subject to underlying Frappe validation and permission rules.

Shared ERPNext enhancements include:

- Optional Arabic/English search for Journal Entry Account selection using `Account.custom_account_name_arabic`, configurable through **Marina Accounting Settings**.
- Optional bilingual warehouse names in supported Stock Entry selectors.
- Configurable Naming Series for Marina operational documents.

Permission Manager does not override native Frappe privilege boundaries.

## 10. POS Reconciliation, bank statements and accounting

The POS Reconciliation module connects **Bank POS Transaction**, **Alhamrani Transaction**, settlement evidence, bank statement entries and ERPNext Journal Entries.

### Import and reconciliation

- Bank POS import and transaction review, terminal references, mapping/configuration and card-type normalization.
- **POS Reconciliation Run** with open-period lifecycle, execution history, period locks, summary KPIs and filterable reconciliation results.
- Matching by payment evidence including reconciliation identity, RRN, transaction date/time, amount, card type and masked-PAN validation.
- Distinct outcomes including **Fully Matching**, **Matching Not Settled**, **Bank Only – Settled / Not Settled**, **Alhamrani Only** and **Discrepancy**.
- Background execution, source record traceability and accounting-state visibility.
- **Connections** document tab for imports, records, period locks and execution history.

### Bank statement and GL matching

- Import **Marina Bank Statement** transactions and reconcile POS settlement components against statement lines.
- Gross deposits, commission charges and VAT-on-commission matching.
- Bank statement ↔ General Ledger matching with evidence-based references and grouped/line-level review.
- Explicit exclusions, manual match/unmatch/reversal safeguards, search/filter controls, settlement statuses and duplicate-prevention checks.
- Statement reconciliation controls that distinguish actual settlement evidence from run-level metadata.

### Manual Alhamrani payment management

The **Actions → Manage Alhamrani Payment** workflow combines previously separate operations:

- Find an Alhamrani transaction by AUP number and inspect its status, Sales Invoice, RRN and existing links.
- Find eligible Bank POS candidates using RRN and date, then validate amount, transaction type and approval status.
- Confirm a terminal-slip payment or correct a previously manually entered RRN when permitted.
- Explicitly select and approve a one-to-one manual Alhamrani ↔ Bank POS link.
- Reuse existing audited enrichment and duplicate-link protection; linked or financially protected transactions cannot be silently rewritten.
- Execute a combined authorized AUP update plus link in one database request so a failure rolls back the operation.
- Display POS Profile/date/time evidence; differences are disclosed for user review rather than silently accepted.

**Restrictions:** the workflow requires the applicable privileged role and Sales Invoice evidence; it does not create a Journal Entry automatically. The repository also contains controlled unlink and enrichment operations with financial-dependency checks.

### Accounting and reports

- Separate accounting eligibility and posting statuses for commission/VAT processing.
- Draft/submit Journal Entry workflows with posting, cancellation and rollback protections.
- POS Bank Settlement, POS Reconciliation Record and bank-statement traceability.
- **POS Reconciliation Results**, **POS Commission by Store and Device**, and **POS Card Type Summary by Store**.
- Financial dashboards, pending receipts and filtered summary totals.

**Operational note:** manual edits to computed reconciliation records do not modify the matching algorithm and can be superseded by reruns. Preserve original payment evidence and use authorized corrective workflows.

Additional technical context: [POS bank statement reconciliation](docs/POS_BANK_STATEMENT_RECONCILIATION_V0_53_0.md).

## 11. Buying, bulk Purchase Receipt and PO variance analysis

Purchasing functionality is integrated into the shared app rather than registered as a separate Frappe business module.

### Bulk Shipment Receiving

- Excel-style pasted item/shipment data with Purchase Order lookup and preview.
- Validation of supplier, company, quantities, item identity and available PO allocations.
- Reviewed/approved receiving lines and draft Purchase Receipt construction.
- Controlled **Receive Without PO** handling for unmatched or closed/completed PO lines, with explicit warehouse, rate, approval and currency requirements.
- Currency consistency, conversion-rate and warehouse/company validation.
- Standard ERPNext Purchase Receipt remains the final stock/accounting document.

### PO Receipt Variance Discount

- **PO Receipt Variance Discount** report and **PO Receipt Variance Matrix** view.
- Supplier, company, Year, Season and Collection filtering.
- PO quantity vs submitted Purchase Receipt quantity across multiple documents.
- **Item Variant** calculation with optional Item Template presentation; shortages in one size do not cancel excess in another.
- Configurable excess allowance (report default currently **8%**) and discount on eligible extra quantity (default **50%**).
- CNY from original PO rates with SAR base-rate display option, subject to transaction currency validation.
- Quantity eligible for discount, value before discount and discount amount totals.
- Style matrix view sorted by highest discount amount, with item size breakdown and product images where available.

The report estimates a commercial supplier claim; it does not automatically amend posted Purchase Receipts or supplier invoices.

## 12. Marina Design Management

Design-to-production module integrated into the same app while retaining its own module identity, workspace and role/permission controls.

### Design master, teams and references

- **Mood Board** and **Design Code** organization by Year, Season, Collection, Drop, Mood Board and fashion category.
- Design team assignments including Designer, Merchandiser, Technical Fitting, QC, sourcing/shipping and related business roles.
- **Factory List**, **Marina Pantone**, **Marina Fashion Category** and document/milestone type reference masters.
- Configurable **Design Management Settings** and designated team defaults.

### Milestones, ownership and follow-up

- **Design Milestone Plan Entry**, **Design Milestone Execution** and **Design Milestone Custody Event**.
- Current/projected/completed milestone tracking, required evidence, assignment and controlled custody transitions.
- Controlled milestone creation, advancement, date corrections and return-to-milestone workflows with audit history.
- **Production Follow-Up Grid** for design/assignee/milestone progress, status/custody filters and multi-code search.
- **Design Management Dashboard** and **Mood Board Overview** report.

### Documents, manufacturing and discussions

- **Design Document** publishing and evidence linking, including designer-specific Tech Pack files and multi-file documents.
- Document publication/revisions and access-controlled attachment download.
- Production item, colorway/size breakdown and ERPNext Item creation workflows.
- **Design Cost Breakdown** with commercial quotations/components, approval and revision controls.
- Design/Mood Board discussions, messages, attachments, unread/notification information and automated milestone activity; attachment access is permission-controlled.

### Design authorization

- **Design Module Role** for organizational identity and eligible custody.
- **Design User Permission** profiles for explicit document Read/Create/Edit/Delete and named action permissions.
- Individual permissions can be enabled per user while preserving legacy fallback for unconfigured users; native Frappe permissions remain an upper bound.
- Design workspace visibility controls and server-side record access checks.

See [Design consolidation reference](docs/DESIGN_MANAGEMENT_CONSOLIDATION_CUTOVER.md) and [individual permission reference](docs/DESIGN_USER_PERMISSIONS_V15_DEMO.md). These documents include historical migration/test instructions, not necessarily the present deployment procedure.

---

## Cross-module data flow

```text
Commercial Calendar + Sales/Stock/Buying Plan
                   |
             Sales Forecasting
                   |
          DC Dispatch / Reallocation
                   |
              Material Request
                   |
            Stock Transfer Control
                   |
       Send -> Transit -> Receive
                   |
           Stock Transfer Audit
                   |
              Cycle Count

Design / Mood Board -> Milestones -> Documents / Costing
                   |
              ERPNext Items
                   |
          Purchase Orders / Receipts
                   |
       PO Receipt Variance Discount

POS Bank + Alhamrani + Bank Statement + General Ledger
                   |
             POS Reconciliation
                   |
         Controlled commission/VAT
             Journal Entries
```

These flows represent integration points, not guaranteed automatic execution of every arrow. Standard ERPNext submission, approval and posting requirements remain in force.

## Installation, migration and deployment

1. Use a compatible **Frappe/ERPNext v15** bench and install the app as `marina_custom_apps` through your normal bench/Frappe Cloud deployment process.
2. Back up the site before significant application upgrades, schema changes or module migrations.
3. Deploy the intended Git commit and run the normal Frappe migration and asset-build process.
4. Verify that registered Module Defs, DocTypes, Pages, Reports and workspaces have synchronized successfully.
5. Check role grants, individual Design permissions, Finance permissions, operational settings, company/warehouse mapping and required integrations.
6. Validate critical workflows on **Demo** before promoting to production: stock transfers, counting, purchasing, POS/bank matching, generated accounting and design milestone custody.

### Safe operation and performance principles

- Stock Ledger Entries and General Ledger Entries remain controlled by ERPNext.
- Server validation and Frappe permissions take precedence over client-side button visibility.
- Reconciliation/accounting and design approvals use audit and financial/source dependency safeguards.
- Avoid rewriting raw terminal-response JSON, existing journal entries or posted stock movements to work around a display mismatch.
- High-volume reports and matching services use scoped searches, batching, pagination and/or background jobs where implemented.
- Automated GitHub checks help prevent regressions but do not replace installed-site runtime/permission UAT.
- **Merging into GitHub `main` does not deploy to Frappe Cloud.**

## Detailed references

- [Sales Forecasting](marina_custom_apps/sales_forecasting/README.md)
- [Marina Calendar](marina_custom_apps/marina_calendar/README.md)
- [SOP Management](marina_custom_apps/sop_management/README.md)
- [POS Bank Statement Reconciliation](docs/POS_BANK_STATEMENT_RECONCILIATION_V0_53_0.md)
- [Design Management Consolidation](docs/DESIGN_MANAGEMENT_CONSOLIDATION_CUTOVER.md)
- [Design Individual Permissions](docs/DESIGN_USER_PERMISSIONS_V15_DEMO.md)

## Maintenance guidance

This README is a **feature inventory at repository level**. When adding a module or major business workflow, update the relevant section and link to a detailed module reference if needed. Do not describe an experimental feature as production-verified merely because its source has been merged. When behavior differs between code and deployed site, record the deployed commit, site app versions and migration status before investigating.
