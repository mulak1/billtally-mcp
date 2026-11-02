# BillTally: Bill Math Checker & Bank Statement Matcher (MCP Connector)

Plain-English supplier bill & receipt math verification, bank statement matching, and multi-tab Microsoft Excel (`.xlsx`) with live `=SUM()` formulas or accounting CSV export.

- **Live Bill & Bank Check Desk:** https://schemaextract-mcp-production.up.railway.app
- **Remote MCP Endpoint (Claude & ChatGPT):** `https://schemaextract-mcp-production.up.railway.app/mcp`
- **User & IT Admin Documentation:** https://schemaextract-mcp-production.up.railway.app/docs
- **About BillTally:** https://schemaextract-mcp-production.up.railway.app/about
- **Privacy & Confidentiality Policy:** https://schemaextract-mcp-production.up.railway.app/privacy
- **Terms of Service:** https://schemaextract-mcp-production.up.railway.app/terms
- **Founder & Creator:** Kader Mula (`mulak1@gmail.com`)

---

## Included MCP Tools (All Read-Only & Idempotent)

1. **`extract_financial_documents` (`Check Supplier Bill & Line-Item Math`)**
   - Extracts supplier name, bill number, issue/due dates, payment terms, currency, line items, subtotal, sales tax, and total from supplier bills, receipts, and statements.
   - Performs cent-level fixed-decimal arithmetic (`sum(line_items) + tax == total`), flags 1099-NEC review items, and drafts a polite supplier correction note when an overcharge is caught.

2. **`reconcile_invoices_with_bank_ledger` (`Match Bills to Bank Statement`)**
   - Matches extracted supplier bills against bank statement withdrawals using date and amount tolerances.
   - Flags matched payments, unpaid bills, bank withdrawals missing a receipt, and duplicate bank charges.

3. **`export_ledger_bundle` (`Export Excel or Accounting CSV Spreadsheet`)**
   - Generates a downloadable 3-tab Microsoft Excel (`.xlsx`) workbook with native `=SUM()` and `=ROUND()` accounting formulas, or a clean CSV file for accounting import.

---

## Connect to Claude

1. Open **Claude Settings → Connectors → Add custom connector**.
2. Name: `BillTally: Bill Math Checker & Bank Statement Matcher`
3. Remote MCP Server URL: `https://schemaextract-mcp-production.up.railway.app/mcp`

## Local Development

```bash
pip install -r requirements.txt
pytest
python -m app.main
```
