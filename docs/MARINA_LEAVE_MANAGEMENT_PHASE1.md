# Marina Leave Management — Phase 1 (read-only)

Branch: `feature/marina-leave-management`

## Scope
Pure accrual calculation and privileged preview endpoint. **No scheduler, hooks,
migration, Leave Allocation creation, ledger modification or background job.**

ERPNext / HRMS remains the source of truth. Preview is **not** a leave balance.

## Assumptions to validate with HR
- Annual 30: 30 / 330 normalized eligible days.
- Annual 21: 21 / 339 normalized eligible days.
- 30 standardized service units per full calendar month, prorated by actual
  calendar days for partial months or absences.
- Earned monthly credit is recognized on the last calendar day of the earning month.
- Joining anniversaries remain available for reporting; there is no annual cap in the monthly preview.
- Only submitted **Approved** Paid Leave and Leave Without Pay exclude accrual.
- Overlapping absences count only once; half days are supported.
- Holiday exclusions in ERPNext applications may differ from calendar spans.
  Preview includes warnings for these cases; reconcile before posting.
- Paid Leave also reduces official HRMS balance; this simulator **only**
  estimates credits, and does not calculate historical ledger balances.
- Rejected applications and test allocation HR-LAL-2024-00001 are not used
  to produce entitlements; no test data is removed.
- Monthly accrual now uses a fixed monthly baseline minus the fraction of that month covered by approved Paid Leave or Leave Without Pay. Prior-month leave and lifetime accrual do not reduce an otherwise full current-month credit.

## Preview in demo console
```python
from marina_custom_apps.marina_leave_management.api import preview_employee
result = preview_employee("HR-EMP-00053", "2026-11-23")
print(result)
```

Endpoint requires an authenticated HR Manager / System Manager with Employee
and Leave Application read permissions. It may return historical dates and
leave-document identifiers; use only in authorized HR sessions.

## Tests
```bash
python -m unittest marina_custom_apps.marina_leave_management.test_accrual
```

## Next acceptance gate
Check leave-day handling (holiday lists and half-days), contract anniversary,
rounding in HRMS allocation, active employee status and historical cutover.
Do not enable any posting until HR validates sample calculations.


## Employee exemptions
A migration patch creates Employee checkbox
`custom_exclude_from_leave_accrual` ("Exclude from Automatic Paid Leave Accrual").
It defaults to unchecked for every employee. HR must explicitly check it on
records that should be exempt, including HR-EMP-00048 and HR-EMP-00023.

When checked, `preview_employee` returns
`excluded_from_accrual: true` and `earned: null` rather than an entitlement.
It does not delete leave history, change a Leave Ledger Entry, or set a balance
to zero. Remote work **does not** automatically cause exclusion; HR must
decide employee by employee.

Migration on demo: deploy branch, run migrations using normal Frappe Cloud
deployment, verify Employee field, manually mark approved exemptions, and
test a preview. No posting job exists in this release.

## Month-end posting policy (2026-11-23 revision)
Accrual is recognized on the last calendar day of each calendar month, including December 31 for annual closing. A partial first month is prorated and also credited on that month's last day. No monthly scheduler or posting automation is enabled yet. The simulator only includes a calendar month when its final day has arrived. For mid-month 'as of' dates the current month's accrual is not included; that requires a separate accrued-but-unposted accounting estimate if requested.

## Fixed monthly accrual clarification (2026-11-24)
- Annual 30: each completed month starts at 30/330*30 = 2.7272727... days.
- Annual 21: each completed month starts at 21/339*30 = 1.8584071... days.
- Monthly credit = monthly baseline * (eligible calendar days / calendar days in that month). The employee's joining month follows the same proration.
- Only approved Paid Leave and Leave Without Pay overlapping that particular month reduce eligible days; overlaps are not double counted.
- The previous contract-year ceiling was removed from the monthly calculator. For example, HR-EMP-00007 must earn 2.727273 for October 2026 given zero October exclusions, irrespective of August leave or historic totals.
- **Policy reconciliation needed before posting:** 12 fully eligible months on Annual 30 now accrue 32.727273, which exceeds its labeled 30-day annual entitlement. The same issue applies to Annual 21. The report must remain provisional until this difference is explicitly resolved.
- No scheduler or automatic posting has been activated.
