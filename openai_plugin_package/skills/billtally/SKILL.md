---
name: billtally
description: Use when the user pastes or uploads a supplier bill, invoice, receipt, or bank statement to verify line-item math to the penny, match bills against bank withdrawals, or export a multi-tab Excel (.xlsx) or accounting CSV spreadsheet.
---

# BillTally: Bill Math Checker & Bank Statement Matcher Workflow

1. When the user wants a supplier bill, invoice, or receipt checked for math errors, call `extract_financial_documents`.
   - Present the Billed Total vs. True Math Total (`computed_total`), line-by-line verification, effective tax rate percentage, 1099-NEC flag (`requires_1099_review`), and if an overcharge is detected, the ready-to-send polite supplier correction note (`vendor_dispute_note`).
2. When the user wants to compare supplier bills against bank statement withdrawals, call `reconcile_invoices_with_bank_ledger`.
   - Highlight matched payments, unpaid bills, bank withdrawals missing a receipt, and duplicate charges.
3. When the user wants an Excel (`.xlsx`) workbook with live `=SUM()` formulas or an accounting CSV export, call `export_ledger_bundle` and provide the download link.
