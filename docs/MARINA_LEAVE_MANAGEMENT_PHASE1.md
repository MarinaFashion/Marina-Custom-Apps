# Marina Leave Management — Phase 1 (read-only)

Branch: `feature/marina-leave-management`

## Scope
Pure accrual calculation and privileged preview endpoint. **No scheduler, hooks,
migration, Leave Allocation creation, ledger modification or background job.**

ERPNext / HRMS remains the source of truth. Preview is **not** a leave balance.

## Assumptions to validate with HR
- Annual 30: 30 / 330 normalized eligible days.
- Annual 21: 21 / 339 normalized eligible days.
- Accrual uses **actual eligible calendar days**, including variations for
  28, 29, 30, and 31-day months. Partial joining months and absences reduce
  the count of eligible calendar days.
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
- Monthly accrual uses actual eligible calendar days multiplied by the per-day rate. Prior-month leave and lifetime accrual do not reduce an otherwise full current-month credit.

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
- Annual 30: monthly credit = actual eligible calendar days * 30/330.
- Annual 21: monthly credit = actual eligible calendar days * 21/339.
- For Annual 30 with no absences: February (28d) = 2.545455; April (30d) = 2.727273; October (31d) = 2.818182. Joining month counts only dates on/after joining.
- Only approved Paid Leave and Leave Without Pay overlapping that particular month reduce eligible days; overlaps are not double counted.
- The previous contract-year ceiling was removed from the monthly calculator. For example, HR-EMP-00007 must earn 2.818182 for October 2026 given zero October exclusions, irrespective of August leave or historic totals.
- **Policy reconciliation needed before posting:** 365 eligible days on Annual 30 now accrue 33.181818, which exceeds its labeled 30-day annual entitlement. The same issue applies to Annual 21. The report must remain provisional until this difference is explicitly resolved.
- No scheduler or automatic posting has been activated.

## Actual calendar-day basis (2026-11-24 revision)
The latest preview rule is daily accrual: `eligible_calendar_days * annual_entitlement / eligible_service_divisor`. Divisors remain 330 for Annual 30 and 339 for Annual 21, pending HR validation. This supersedes the prior fixed 30-day monthly baseline. It deliberately DOES NOT reintroduce the anniversary cap, so full months are independent. The annual entitlement discrepancy remains: an absence-free 365-day year gives 33.181818 days for Annual 30 and 22.610619 days for Annual 21. Do not post to HRMS until resolved.

## Approved service-day accrual interpretation (2026-11-24; supersedes older numeric examples)
- **No annual accrual cap.** More eligible service than the nominal annual baseline earns additional Paid Leave; the earnings carry forward.
- The daily rate for each **joining-anniversary year** is `annual leave entitlement / (calendar days in that anniversary year - annual leave entitlement)`.
- Annual 30: `30/335` for a 365-day anniversary year; `30/336` for a 366-day anniversary year.
- Annual 21: `21/344` for a 365-day anniversary year; `21/345` for a 366-day anniversary year.
- At each calendar month end, credit that month's actual eligible days multiplied by the relevant anniversary-year daily rate. An anniversary inside the month can split the monthly calculation between two rates.
- Approved Paid Leave and Leave Without Pay stop accrual for the overlapping calendar days; other periods are treated as eligible under current policy. Paid Leave also independently consumes leave from the actual HRMS balance.
- For 365 days with 30 Paid Leave days, 335 eligible days earn exactly 30. For two complete 365-day years with 60 excluded days, 670 eligible days earn 60. With only 30 excluded days across two years, 700 eligible days earn 62.686567, not exactly 60.
- The previous 30/330, 21/339, fixed-month, and anniversary-cap assumptions in earlier sections are **superseded** by this rule. Existing historical simulations will change after deployment. HR retains authority to validate historical balances.
- Preview and reconciliation only. No automatic Leave Allocation, payroll valuation, or Leave Ledger posting is enabled.
