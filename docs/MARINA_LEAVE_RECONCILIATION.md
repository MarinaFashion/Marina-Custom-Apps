# Marina Leave Reconciliation — read-only report

## Demo deployment
Deploy `feature/marina-leave-management` on
`marinademo.frappe.cloud` and run the normal Frappe Cloud migration.
Open **Marina Leave Reconciliation** from ERPNext Report List or directly:
`/app/query-report/Marina%20Leave%20Reconciliation`.

Requires HR Manager or System Manager and read access to Employee and
Leave Application. Report provides As Of, Employee, Contract Entitlement,
and Show Exempt Employees filters.

## Important limitations
- This is a **provisional simulation**, not an official Leave Balance report.
- 30/330 and 21/339 standardized eligible-day formulas are still subject
  to HR/legal validation. Monthly credits are not restricted by annual caps.
- The simulation assumes the current contract entitlement applies from
  joining date; historic 21-to-30 transitions cannot yet be reconstructed.
- Calendar-day exclusions may differ from leave days defined by an ERPNext
  Holiday List; preview warnings highlight obvious discrepancies.
- Only submitted **Approved** Paid Leave and Leave Without Pay exclude
  accrual; rejected applications do not.
- Credits and debits are summarized using ledger effective dates. Paid Leave
  ledger debits spanning the cutoff are flagged and omitted in full.
- The known test allocation `HR-LAL-2024-00001` is excluded entirely,
  including both +73 and -50 ledger entries. Original records remain intact.
- Leave taken outside ERPNext may be absent from historical data.
- Long-service employee calculations require historical contract and leave
  record verification. Proposed credits must NOT be posted automatically.
- HR exemptions are managed via Employee field
  `custom_exclude_from_leave_accrual`, NOT by job title or remote status.
  Exempt records show **no calculation**, not a zero balance.
- `Provisional Unposted Credit` = simulator earned - non-test ledger
  credits recognized in preview. It is NOT an approved accounting adjustment.
- `Indicative Balance` = simulator earned + recognized ledger application
  debits. It is NOT the ERPNext period-specific available leave balance.

## Demo smoke tests
1. Verify report loads without SQL/write errors, and only authorized roles
   can view. Check filtering for Annual 21 and Annual 30.
2. Mark HR-EMP-00048 and HR-EMP-00023 exempt **manually** only after HR
   confirms. Verify blank earned/balance and Exempt status.
3. Check HR-EMP-00018 and HR-EMP-00010 against previous simulations.
4. Inspect notes for ledger spanning cutoff, older records, holidays and
   historical contract changes.
5. Run regression tests in a bench console:

```python
import unittest
from marina_custom_apps.marina_custom_apps.report.marina_leave_reconciliation import test_marina_leave_reconciliation
suite = unittest.defaultTestLoader.loadTestsFromModule(test_marina_leave_reconciliation)
result = unittest.TextTestRunner(verbosity=2).run(suite)
print(result.testsRun, len(result.failures), len(result.errors))
```

## Release gate
No scheduler, no leave allocation, no historical credit posting.
Review business formula and employee history before authorizing changes.

## Month-end posting policy (2026-11-23 revision)
Accrual is recognized on the last calendar day of each calendar month, including December 31 for annual closing. A partial first month is prorated and also credited on that month's last day. No monthly scheduler or posting automation is enabled yet. The simulator only includes a calendar month when its final day has arrived. For mid-month 'as of' dates the current month's accrual is not included; that requires a separate accrued-but-unposted accounting estimate if requested.

## Fixed monthly accrual clarification (2026-11-24)
- Annual 30: monthly credit = actual eligible calendar days * 30/330.
- Annual 21: monthly credit = actual eligible calendar days * 21/339.
- For Annual 30 with no absences: February (28d) = 2.545455; April (30d) = 2.727273; October (31d) = 2.818182. Joining month counts only dates on/after joining.
- Only approved Paid Leave and Leave Without Pay overlapping that particular month reduce eligible days; overlaps are not double counted.
- The previous contract-year ceiling was removed from the monthly calculator. For example, HR-EMP-00007 must earn 2.818182 for October 2026 given zero October exclusions, irrespective of August leave or historic totals.
- **Policy reconciliation needed before posting:** 365 eligible days on Annual 30 now accrue 33.181818, which exceeds its labeled 30-day annual entitlement. The same issue applies to Annual 21. The report must remain provisional until this difference is explicitly resolved.
- No scheduler or automatic posting has been activated.

## Actual calendar-day basis (2026-11-24 revision)
The latest preview rule is daily accrual: `eligible_calendar_days * annual_entitlement / eligible_service_divisor`. Divisors remain 330 for Annual 30 and 339 for Annual 21, pending HR validation. This supersedes the prior fixed 30-day monthly baseline. It deliberately DOES NOT reintroduce the anniversary cap, so full months are independent. The annual entitlement discrepancy remains: an absence-free 365-day year gives 33.181818 days for Annual 30 and 22.610619 days for Annual 21. Do not post to HRMS until resolved.
