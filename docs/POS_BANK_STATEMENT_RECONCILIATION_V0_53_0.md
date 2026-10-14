# v0.53.0 Experimental — SNB Bank Statement Reconciliation

This branch adds the first testable implementation of the third reconciliation layer:

1. POS / ERP card transaction evidence
2. Alhamrani reconciliation and commission/VAT posting
3. SNB bank statement reconciliation

## Scope in this experimental branch

- Uses standard ERPNext **Bank Transaction** as the SNB statement source.
- Builds **POS Bank Settlement** groups from the latest confirmed POS reconciliation evidence.
- Settlement identity: Bank Account + Settlement Number + bank terminal reference + unified Card Type.
- Bank terminal reference defaults to the first 8 digits of the POS Terminal ID and is configurable.
- Parses configured SNB description codes into Gross / Commission / VAT components.
- Matches statement lines to settlement groups and compares Gross, Commission, VAT, and Net independently.
- Leaves non-POS statement lines in standard ERPNext Bank Transaction for normal ERPNext Bank Reconciliation against Payment Entry / Journal Entry / other supported vouchers.
- Does not create income, expense, or additional Journal Entries.
- Does not automatically mark standard ERPNext Bank Transactions as reconciled.

## Seeded demo code mappings

The migration seeds the codes observed in Marina's provided SNB example:

| Code | Card Type | Component |
|---|---|---|
| SM | MADA | Gross |
| FS | MADA | Commission |
| VS | MADA | VAT |
| VC | VISA | Gross |
| FV | VISA | Commission |
| VV | VISA | VAT |

These are configurable in **POS Reconciliation Settings** and should be verified against more SNB statements before production use.

## Demo workflow

1. Import or create the SNB statement as standard ERPNext **Bank Transaction** records.
2. Open **POS Bank Statement Reconciliation**.
3. Select the ERPNext Bank Account and statement date range.
4. Save.
5. Click **Build & Match**.
6. Open **POS Bank Settlements** from the View menu.
7. Review Fully Reconciled, Partial, Amount Difference, and ERP Settlement Only results.
8. Use standard ERPNext Bank Reconciliation for statement lines classified as Other Bank Statement Lines.

## Important limitation of this first branch

This release provides POS settlement evidence matching. It intentionally does not yet automate matching non-POS bank statement lines to Payment Entries or Journal Entries; ERPNext's standard Bank Reconciliation remains the control for those lines.
