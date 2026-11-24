# Phase 4C — Controlled Paid Leave posting pilot (DEMO ONLY)

**Scope:** One explicitly selected pilot employee per approved monthly accrual
batch. Not a production release. No scheduler or full-batch posting.

## Preconditions
- Site: `marinademo.frappe.cloud` ONLY. Server enforces demo hostname.
- HRMS: 15.64.9 is the inspected reference version.
- `Paid Leave.is_earned_leave=0`; no global HRMS scheduler disabled.
- Approved, unchanged accrual candidate: positive credit and `Ready for Approval`.
- HR Manager or System Manager with Employee and Leave Allocation permissions.
- Open **Marina Leave Management Settings** and explicitly set:
  - **Pilot Employee** to an eligible employee with no other Paid Leave
    allocations/credits for the first credit (e.g. HR-EMP-00001 only if
    independently confirmed)
  - **Cutover Date** equal to approved first month-end (e.g. 2026-10-31)
  - **Allocation Valid Until** to a reviewed HRMS allocation end date
  - **Historical Cutover Reviewed** only after HR's review of opening balances
  - **Enable Leave Posting** only when actual demo pilot is authorized
- Setting is **OFF on deployment**. Saving it with missing prerequisites fails.

## Batch actions
- **Check Posting Readiness**: read-only preflight
- **Dry Run Selected Employee**: read-only calculation, requires pilot
  employee/cutover settings but does not require enable switch
- **Post Selected Employee (Demo Pilot)**: presents dry run, then a separate
  explicit confirmation before posting. Actual posting additionally requires
  enabled setting. All controls enforced on server, not only JavaScript.

## Posting algorithm
1. Lock Employee and batch rows for serialization (database row locks).
2. Reload approved snapshot and re-evaluate current accrual.
3. Enforce site, pilot, paid-leave setting, cutover, chronology and eligibility.
4. Assert deterministic journal key is unused (database unique constraint).
5. Calculate six-decimal exact accrual, three-decimal HRMS increment and
   carry-forward rounding residual from the last *posted* journal.
6. Insert a Pending Marina Leave Posting Journal; if this is the first
   credit create+submit a **non-carry-forward** Leave Allocation starting on
   the cutover month-end and ending on the explicitly configured date.
   For a following consecutive month, update the same submitted allocation
   using HRMS `on_update_after_submit` (never write Leave Ledger directly).
7. Verify that cumulative non-carry-forward submitted allocation-ledger
   credits exactly match expected cumulative credits.
8. Mark the journal Posted with linked allocation in the **same transaction**.
   Error rolls back the allocation and journal to a savepoint. Normal Frappe
   request commits only on successful completion.
9. Changes in allocation period, unrelated allocation credits or nonsequential
   month posting stop the pilot for manual investigation.

## IMPORTANT policy boundaries
- **No historical opening balance is automatically synthesized or credited.**
  If HR wishes historical balances to be recognized, design an audited
  opening-balance migration separately BEFORE wider posting.
- The long/continuous allocation period is **only a controlled pilot**. An
  HRMS-supported renewal strategy, unlimited accumulation, termination and
  end-of-period effects require longitudinal testing.
- The posting service has NO batch-wide operation. Don't copy pilot settings
  to production. This release never enables production posting.
- Prior test allocation `HR-LAL-2024-00001` is untouched.

## Deployment verification (read-only)
Deploy this branch to demo, migrate, restart services. Do not enable posting.

```python
import frappe
frappe.db.rollback()
print("Journal:", frappe.db.exists("DocType", "Marina Leave Posting Journal"))
print("Settings:", frappe.db.exists("DocType", "Marina Leave Management Settings"))
print("Earned:", frappe.db.get_value("Leave Type", "Paid Leave", "is_earned_leave"))
print("Enabled:", frappe.db.get_single_value("Marina Leave Management Settings", "enable_leave_posting"))
print("Journal count:", frappe.db.count("Marina Leave Posting Journal"))
print("Database changes: NONE")
```

Read-only plan: Configure pilot employee/cutover/end date but leave Enable
Posting off. Run **Dry Run Selected Employee**. The output must show month-end,
new allocation, exact 6dp, HRMS 3dp, residual, and no database modifications.

**STOP POINT:** Do not enable or click Post Selected Employee until the user
explicitly approves the pilot employee and allocation end date after seeing
the dry run.

## Manual pilot acceptance criteria (after authorization)
- First posting creates exactly one submitted Leave Allocation and one
  corresponding submitted non-carry-forward allocation credit.
- Journal status Posted, linked to allocation, unique employee/month key.
- Retry same month raises an error and makes no additional ledger credit.
- Failed transaction leaves no partial journal or allocation.
- Posting subsequent consecutive month credits the same allocation via
  post-submit update, residual survives, and ledger totals reconcile.
- Paid leave applications correctly debit the allocated available balance.
- Cutover does not rewrite any historical leave application or allocation.
