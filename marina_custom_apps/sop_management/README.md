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