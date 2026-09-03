# Marina Calendar

App-managed calendar foundation for Marina Custom Apps.

## Source of truth

- `Marina Calendar Date`: one row per Gregorian date with Hijri attributes and a read-only Events child table.
- `Marina Calendar Event`: the editable source of truth for events. Events can span a date range and can be scoped to Company, City or Branch, with an optional Main Group.
- `Marina Calendar Date Event`: read-only synchronized child rows shown on each date.

Changing, disabling or deleting a Calendar Event automatically rebuilds the affected Calendar Date child rows. Users should never maintain the child rows manually.

## Legacy migration

On install/migrate the module auto-detects the existing custom calendar by its confirmed fields (`date`, `hijri_date`, `hijri_m_name`, `day`, `month`, `year`, and optional `event`). It copies date/Hijri records into `Marina Calendar Date` without deleting or modifying the legacy custom DocType.

Existing single-text events are imported into `Marina Calendar Event`; consecutive dates carrying the same legacy event text are grouped into one ranged event. Imported events are classified as `Other` / `Unknown` rather than guessing business meaning. The old calendar remains intact as a rollback source until UAT is complete.

Sales Forecasting v0.43.1 prefers Marina Calendar automatically and context-filters Company/City/Branch and Main Group events before building historical or future forecast features.
