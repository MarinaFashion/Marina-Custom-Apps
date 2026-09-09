# Marina SOP Management — Phase 1

Phase 1 is a self-contained module inside **Marina Custom Apps**.

## Included

- SOP Type
- SOP Document
- SOP Version
- SOP Section child table
- Controlled Draft → Under Review → Approved → Published lifecycle
- Immutable Published/Superseded versions
- Automatic superseding of the previous published version
- Create New Version action that copies the current published sections
- English / Arabic / Bilingual content
- SOP Library Desk page for published SOPs
- SOP Manager / SOP Editor / SOP Viewer roles
- Default SOP Types: Policy, Procedure, Work Instruction, Guideline, Checklist
- Unified **Marina Custom Apps** umbrella workspace

## Workspace strategy

The umbrella workspace is additive. Existing module workspaces are not deleted.
Links are filtered during migration so a Demo/Live bench does not receive broken
shortcuts to a Marina module that is not installed there.

## Phase 1 boundaries

This foundation intentionally does not yet add acknowledgements, employee
read-and-understood tracking, scheduled review reminders, training assignments,
advanced approval matrices, document attachment governance, or SOP analytics.
Those belong to later SOP phases after the Phase 1 lifecycle is validated.
## v0.44.0 Phase 1 integration

- SOP Management is integrated into Marina Custom Apps as a first-class module.
- Published/Superseded SOP Versions are immutable and cannot be deleted.
- Published SOP Documents cannot be deleted; archive is the controlled lifecycle.
- SOP Library navigation uses Frappe Desk route options correctly.
- Marina Custom Apps becomes the umbrella workspace while specialist workspaces remain available.
### Phase 1 control hardening

- Server-enforced lifecycle transitions prevent REST/API users from bypassing Draft â†’ Review â†’ Approval â†’ Publication.
- Published SOPs use a controlled Archive action instead of deletion.
- SOP Library search uses permission-respecting queries so restricted document metadata is not leaked.
## v0.44.1 Draft version creation fix

- Draft SOP Versions may be created and saved before content is entered.
- Required language content is enforced when submitting a Draft for review.
- Open in SOP Library is shown only when the SOP has a published current version.
## v0.45.0 Professional controlled-document presentation

- SOP Section content remains rich HTML via Frappe Text Editor fields.
- Word/Excel tables pasted into rich content are rendered with controlled Marina table styling in the Library and Print/PDF output.
- A standard `Marina SOP Controlled Document` Jinja Print Format is created idempotently during install/migrate.
- The controlled format supplies Marina branding, metadata header, colored section headings, table borders/header styling, revision history, and a controlled-document footer.
- SOP Version includes a `Document Preview` action.
- Published SOP Library includes `Print / PDF` and renders the same controlled visual hierarchy.
- Revision History is generated from SOP Version records rather than manually typed by users.

The presentation layer intentionally standardizes fonts, headings, metadata and table appearance so authors focus on content rather than manually formatting every document.
### Advanced HTML authoring

- `Content Mode` can be `Standard Rich Text` or `Advanced HTML`.
- Advanced HTML uses an HTML source editor and a server-sanitized live preview.
- Frappe HTML sanitization is forced on every save/preview.
- JavaScript, unsafe event attributes and dangerous markup are not trusted.
- Images must be uploaded to ERPNext Files and use `/files/` or `/private/files/`; remote and base64/data images are rejected.
- Advanced HTML controls the document body only. Marina branding, metadata, approval/version information, revision history and footer remain controlled by the system.
- The same sanitized body is used by SOP Library and controlled Print/PDF output.