# POS / SNB Bank Statement Reconciliation v0.53.0

## Final experimental architecture

v0.53.0 uses one operational reconciliation workflow: **POS Reconciliation Run**.

The run combines three evidence sources:

1. Marina / Bank POS Transaction
2. Alhamrani Transaction
3. Marina Bank Statement Transaction (custom statement ledger)

The earlier **POS Bank Statement Reconciliation** doctype is deprecated experimental scaffolding. It remains in the branch only for non-destructive compatibility with Demo data and is no longer the active workflow.

## Custom statement model

### Marina Bank Statement Import
Imports the original SNB XLSX statement directly. It:
- preserves the raw description/reference columns,
- converts debit amounts to positive withdrawals,
- prevents duplicate source rows with a deterministic source key,
- parses POS settlement metadata from RECON NO / REFERENCE / statement codes,
- creates Marina Bank Statement Transaction rows.

### Marina Bank Statement Transaction
This is the module-owned bank statement ledger. It is intentionally independent from ERPNext standard Bank Transaction allocation/status architecture.

POS statement rows are parsed into:
- Settlement Number
- 8-digit Bank Terminal Reference
- Reconciliation Date
- Card Type
- Component: Gross / Commission / VAT

Reconciliation Status:
- Unreconciled
- Partially Reconciled
- Reconciled
- Excluded

When a POS settlement is fully confirmed, the related custom statement Gross / Commission / VAT rows are marked **Reconciled**. Other statement rows remain **Unreconciled** for later Payment Entry / Journal Entry / transfer reconciliation.

## Unified POS Reconciliation Record status

### Match Status
- Fully Matching
- Matching Not Settled
- Discrepancy
- Bank Only
- Alhamrani Only

### Resolution Status
- Auto Cleared
- One Side Matching
- Pending
- Manually Cleared

Rules:

- POS = Alhamrani + statement settlement fully reconciled
  - Match Status = Fully Matching
  - Resolution = Auto Cleared

- POS = Alhamrani + statement settlement not yet fully reconciled
  - Match Status = Matching Not Settled
  - Resolution = One Side Matching

- POS exists, Alhamrani missing
  - Match Status = Bank Only
  - Resolution = Pending
  - Finance may manually clear only after the POS settlement is Fully Reconciled to the bank statement.

- Alhamrani exists, POS missing
  - Match Status = Alhamrani Only
  - Resolution = Pending

- POS / Alhamrani comparison differs
  - Match Status = Discrepancy
  - Resolution = Pending

## Settlement identity

The validated SNB settlement identity is:

**Bank Account + Settlement Number + 8-digit Terminal Reference + Reconciliation Date + Card Type**

The YYMMDD suffix in the SNB POS statement code is the terminal reconciliation date.

Validated statement code mappings:

| Code | Card | Component |
| --- | --- | --- |
| SM | MADA | Gross |
| FS | MADA | Commission |
| VS | MADA | VAT |
| VC | VISA | Gross |
| FV | VISA | Commission |
| VV | VISA | VAT |
| MC | MASTERCARD | Gross |
| FM | MASTERCARD | Commission |
| VM | MASTERCARD | VAT |
| GN | GCCCARD | Gross |
| GF | GCCCARD | Commission |
| GV | GCCCARD | VAT |
| AX | AMEX | Gross |
| AF | AMEX | Commission |
| AV | AMEX | VAT |

## Settlement 263 validation sample

Terminal reference: 55621023  
Reconciliation date: 2026-09-25

MADA:
- 6 POS transactions
- Gross 344.00
- Commission 1.72
- VAT 0.26
- Net 342.02

VISA:
- 4 POS transactions
- Gross 188.00
- Commission 2.53
- VAT 0.38
- Net 185.09

Both card groups were validated at 100% against the supplied SNB statement.

## Accounting control

Accounting eligibility is now based on the unified Resolution Status.

Eligible:
- Auto Cleared
- Manually Cleared

Not eligible:
- One Side Matching
- Pending

This prevents commission/VAT accounting from being treated as confirmed before the three-source control is complete, unless Finance explicitly clears a supported Bank Only exception.

## Internal audit layer

POS Bank Settlement remains an internal evidence object. Users do not need to create it manually.

It groups the underlying POS transactions and corresponding statement Gross / Commission / VAT rows and provides the auditable amount comparison behind the unified POS Reconciliation Record status.

## Standard ERPNext Bank Transaction

ERPNext standard Bank Transaction is no longer the statement source for this custom POS workflow. Existing standard Bank Transactions on Demo are not modified or consumed by the unified v0.53.0 process.
