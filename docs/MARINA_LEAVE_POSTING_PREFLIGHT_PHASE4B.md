# Marina Leave Management Phase 4B — HRMS Posting Preflight

This is a safety-first step **toward** controlled posting. **No HRMS Leave
Allocation or Leave Ledger Entry posting is implemented in this commit.**

## Deployed artifacts
- Marina Leave Management Settings (Single DocType), checkbox
  `Enable Leave Posting` defaults to 0. Server validation currently
  **rejects enabling it** while the mandatory posting safeguards are absent.
- Approved Marina Leave Accrual Batch: **Actions → Check Posting Readiness**.
  Select a positive-credit employee and run an on-demand **read-only** preflight.
- `marina_custom_apps.marina_leave_management.posting_preflight.preview_employee_posting`
  validates HR access, approved batch, unchanged employee candidate, positive
  credit, employee status, exclusions, existing allocation windows, and HRMS
  Paid Leave type settings.

## Important HRMS warning
Frappe HR's standard earned-leave scheduler runs independently of Marina.
The demo Paid Leave type is configured as `is_earned_leave=1` (Monthly).
If Marina credits the same days and HRMS's standard allocation mechanism
also runs, employees may be double-credited. Native Leave Allocation /
earned-leave lifecycle must be experimentally verified on the **demo site**
before a posting engine is released.

The preflight intentionally includes hard blockers for:
- Native earned-leave conflict (if enabled)
- Unresolved historical opening balance cutover
- Missing employee/month posting journal and idempotency key
- Unverified fractional credit behavior and Leave Allocation lifecycle
- Existing active submitted allocations spanning the credit date
- Any stale candidate, inactive/exempt employee, or zero credit

Do **not** turn off native earned-leave behavior in production or change the
Paid Leave DocType during this preflight: first inspect active leave schedules
and allocations on the demo.

## Deploy and test
Deploy `feature/marina-leave-management` to `marinademo.frappe.cloud` and
run the usual migration.

1. Open approved batch `MLAB-20261031-5C9EBDAF3CA3`.
2. Click **Actions → Check Posting Readiness** and choose **HR-EMP-00007**.
3. Note `monthly_credit`, `blocking_reasons`, `earned_leave_frequency`,
   `overlapping_allocations` and `allocation_ledger_count`.
4. Open **Marina Leave Management Settings**. The posting option is off.
   It cannot be switched on until Phase 4B posting implementation passes tests.
5. Confirm there are no new Leave Allocation/Leave Ledger Entry records.

### Alternate read-only console call
```python
from marina_custom_apps.marina_leave_management.posting_preflight import preview_employee_posting

result = preview_employee_posting(
    "MLAB-20261031-5C9EBDAF3CA3", "HR-EMP-00007"
)
print(result)
print("Database changes: NONE")
```

## Next implementation gate
Before **actual** employee-level demo posting is added:
- Test the site's installed HRMS v15 Leave Allocation behavior with earned
  leave and fractional precision, including submit/cancel and backdating.
- Agree on an opening balance cutover and disable any conflicting native
  earned-leave credit process **without interfering with other Leave Types**.
- Implement durable, unique employee + leave type + credit date posting
  reference, linked standard Leave Allocation/Leave Ledger records, and
  recovery from partial failure; use a database lock during posting.
- Prove the same employee cannot be credited twice by retry or alternate
  batches and that a zero-credit employee is never posted.
- Only then allow the settings switch and a **separate** Post Selected Employee
  action with explicit confirmation and audit logging.
