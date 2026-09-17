# Marina Calendar

App-managed calendar foundation for Marina Custom Apps.

## Source of truth

- `Marina Calendar Date`: one row per Gregorian date with Hijri attributes and a read-only Events child table.
- Calendar dates support the standard Data Import Tool. The Gregorian date is the document name, and duplicate dates are rejected by server validation.
- `Marina Calendar Event`: the editable source of truth for events. Events can span a date range and can be scoped to Company, City or Branch, with an optional Main Group.
- `Marina Calendar Date Event`: read-only synchronized child rows shown on each date.

Changing, disabling or deleting a Calendar Event automatically rebuilds the affected Calendar Date child rows. Users should never maintain the child rows manually.

Calendar dates and their Hijri attributes are maintained directly by users. The module does not import records from an older Calendar DocType.

From a Calendar Date, users can select **New Event for This Date** to open a new Calendar Event prefilled with that date. Saving the Event synchronizes it back to the Calendar Date. This shortcut does not make Calendar Date the source of truth.

Sales Forecasting v0.43.1 prefers Marina Calendar automatically and context-filters Company/City/Branch and Main Group events before building historical or future forecast features.

## Calendar view and trading status (v0.43.2)

`Marina Calendar Event` is registered as a native Frappe Calendar so users can switch between Month, Week and Day views. The Calendar keeps Frappe's filter bar; `Event Type` is a standard filter, along with Scope, Branch, City, impact, forecast relevance and Store Trading Status. Calendar rendering treats Marina's End Date as inclusive.

`Store Trading Status` distinguishes a normal event from an operational closure. `Closed` events are automatically forecast-relevant and negative/high impact. For an affected Branch/City/Company scope, Sales Forecasting excludes closed days from normal-demand analog learning and forces future forecast sales/units to zero. `Partially Open` does not guess a sales reduction; it lowers confidence and leaves the commercial effect to historical evidence until a calibrated capacity rule is introduced.
