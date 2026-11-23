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
- Earned monthly credit appears on the next calendar month's first day.
- Join-date anniversaries define entitlement periods and annual caps.
- Only submitted **Approved** Paid Leave and Leave Without Pay exclude accrual.
- Overlapping absences count only once; half days are supported.
- Holiday exclusions in ERPNext applications may differ from calendar spans.
  Preview includes warnings for these cases; reconcile before posting.
- Paid Leave also reduces official HRMS balance; this simulator **only**
  estimates credits, and does not calculate historical ledger balances.
- Rejected applications and test allocation HR-LAL-2024-00001 are not used
  to produce entitlements; no test data is removed.
- Business decision remains open: guaranteed full entitlement at anniversary
  versus excluded leave periods and their effect on eligible service.

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
