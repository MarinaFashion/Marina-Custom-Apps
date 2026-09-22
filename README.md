# Marina Custom Apps

Umbrella Frappe / ERPNext custom application for **Marina Trading Company**.

Marina Custom Apps consolidates Marina's inventory planning, stock-transfer execution, transit control, and post-transfer auditing into one maintained Frappe application.

The **Marina Custom Apps** workspace is a neutral navigation parent. Its child
workspaces remain independently protected by Frappe module access, Workspace
Roles, and DocType permissions. Administrator-added Workspace Roles are
preserved during app migrations.

---

## Included Modules

| Module | Purpose |
| --- | --- |
| **Stock Transfer Control** | Controls and validates physical stock transfers between DC, stores, and transit warehouses. |
| **Stock Transfer Audit** | Reconciles sent vs received quantities and manages transfer discrepancies. |
| **DC Dispatch** | Plans the initial dispatch of new merchandise from the Distribution Center to stores. |
| **Stock Auto Allocation** | Reallocates existing stock between DC and stores based on sales performance, availability, and sell-through potential. |
| **Permission Manager** | Provides System Managers with bulk user role, role permission, module, Workspace, Page, Report, and User Permission controls. |

---

## Permission Manager transition

Permission Manager v0.5.0 (source commit `e512f16`) is integrated into this app
without changing its
Desk routes or the names of its standard records. Existing Custom DocPerm,
Custom Role, Block Module, Workspace Role, and User Permission records remain
Frappe-owned data and are reused. During the transition, migrate Marina Custom
Apps before removing the standalone `marina_permission_manager` app. After the
standalone app is removed, run migrate again so Marina Custom Apps recreates
and takes ownership of the shared module assets.

The User Role Manager provides Role → Users and User → Roles views. Role Profile users are read-only there; direct assignments save through Frappe User validation.

Page and Report Permissions can bulk-convert Open-to-All resources to an exact
explicit role list. The conversion requires at least one enabled non-automatic
role, skips resources that were changed concurrently, and clears permission
caches after the atomic update.

Operational document identifiers use configurable Naming Series. The v0.47.20
migration resets each Marina operational series once so its next generated
number starts at `00001`; existing document names are not renamed.

---

## 1. Stock Transfer Control

Central execution and validation layer for all controlled stock movements.

### Main Functions

- Controls **Send Stock**, **Receive Stock**, and **Transfer Between** transactions.
- Applies role-based transfer permissions.
- Validates Physical Warehouse ↔ Transit Warehouse routes.
- Controls **Material Request → Stock Entry** execution.
- Prevents users from changing the route defined by the Material Request.
- Controls the **End Transit** receiving workflow.
- Tracks actual physical received quantities and discrepancies.
- Prevents unauthorized direct store-to-store transfers.
- Provides the common execution layer used by DC Dispatch, Stock Auto Allocation, and Stock Transfer Audit.

---

## 2. Stock Transfer Audit

Post-transfer reconciliation and discrepancy-management module.

### Main Functions

- Creates audit runs using a configurable date range.
- Compares sent quantity with actual received quantity.
- Identifies shortages, excess quantities, item-level discrepancies, and unexpected received items.
- Supports **Return Discrepancy to Source**.
- Supports **Send Discrepancy to Target**.
- Maintains traceability to the original Send Stock and Receive Stock transactions.
- Provides operational reports and KPIs including:
  - Open Transit Aging
  - Pending Audit Variance
  - Variance Summary
  - Receiver Performance
  - Ignore Analysis

---

## 3. DC Dispatch

Planning module for the **first dispatch of newly received merchandise from the Distribution Center to stores**.

### Main Functions

- Filters merchandise by Year, Season, Collection, Drop, Display Date, Item Group, and Item Subgroup.
- Uses historical sales performance to estimate store demand.
- Supports store tiers and priority sequence.
- Supports minimum display quantities and store min/max limits.
- Supports planner-defined dispatch percentages.
- Preserves received size / variant distribution.
- Generates store-level allocation proposals.
- Generates **Material Requests** for approved allocations.
- Hands execution to **Stock Transfer Control**.

### Process

```text
Historical Sales
      ↓
DC Dispatch Run
      ↓
Allocation Proposal
      ↓
Approval
      ↓
Material Request
      ↓
Stock Transfer Control
```

---

## 4. Stock Auto Allocation

Advanced stock-reallocation engine designed to improve **availability, sell-through, and inventory concentration** after merchandise has already been distributed.

The integrated module is based on the tested **Full Reallocation Engine v1.6.0**.

### Main Functions

- Supports **DC → Store** allocation.
- Supports **Store → Store** reallocation.
- Calculates demand using historical sales, daily sales velocity, days of cover, and current stock.
- Protects source-store inventory based on sales performance.
- Prioritizes complete size / variant availability before additional depth.
- Concentrates limited stock into stronger-performing stores when stock cannot support every store.
- Supports configurable minimum display quantities.
- Supports **New Release Grace Period** protection.
- Supports stores with immature sales history through minimum-display mode.
- Uses store distance and economic routing when selecting donor stores.
- Supports minimum direct-transfer quantities.
- Supports city-level shipment consolidation.
- Creates **Transfer Shipment Batches** for qualifying consolidated routes.
- Generates Material Requests for approved transfers.
- Hands execution to **Stock Transfer Control**.

---

## Integrated Inventory Flow

```text
DC Dispatch / Stock Auto Allocation
              ↓
       Material Request
              ↓
    Stock Transfer Control
              ↓
 Send Stock → Transit → Receive Stock
              ↓
      Stock Transfer Audit
              ↓
   Corrective Transfer, if required
```

---

## Architecture Principles

- **Planning modules plan; Stock Transfer Control executes.**
- Material Requests define the intended stock-movement route.
- Controlled Material Request routes cannot be rewritten during Stock Entry creation.
- Transit warehouse routing is centrally controlled.
- Standard ERPNext stock ledger quantities remain authoritative.
- Actual physical receiving discrepancies are recorded separately for audit.
- Unexpected received items do not create unintended Stock Ledger Entries.
- Server-side validation is authoritative.
- Client-side JavaScript is primarily used for workflow and user experience.
- All planning modules share the same transfer-control and audit foundation.

---

## Current Version

### v0.30.0

Current integrated modules:

1. Stock Transfer Control
2. Stock Transfer Audit
3. DC Dispatch
4. Stock Auto Allocation

**v0.30.0** integrates the tested Stock Auto Allocation Full Reallocation Engine into Marina Custom Apps and connects it to the existing transfer-control and audit architecture.

---

## Platform

Designed for:

- Frappe Framework
- ERPNext
- Marina Trading Company retail and inventory operations
