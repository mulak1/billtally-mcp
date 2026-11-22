"""
Phase 1 & Phase 2 Verification Suite (`tests/test_phase1_phase2.py`):
- MCP `prompts/get` & `resources/read` (fixing `-32601` gap) + 0-input demo prompt
- Raw bank CSV/text reconciliation + 1-call `audit_and_export_pack` compound MCP tool
- Shareable 14-day Verified Audit / Dispute Links (`/v/{audit_id}`, XSS escaping, 404 on invalid/expired)
- Big-4 style "VERIFIED BY BILLTALLY" Excel Audit Cover Sheet (preserving Row 2..N+2 formulas)
- 4 Vertical Organic Destination Pages + JSON-LD + `/sitemap.xml` + `/robots.txt` (zero Reddit features)
- Web Desk privacy badge, Wipe Session Now button, and Verified Dispute Link controls
"""

import io
import time

from fastapi.testclient import TestClient
import openpyxl
import pytest

from app.audit_links import _AUDIT_STORE, create_audit_link
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_mcp_prompts_get_and_resources_read(client: TestClient):
    # prompts/list includes new 0-input demo prompt
    plist = client.post("/mcp", json={"jsonrpc": "2.0", "id": 10, "method": "prompts/list", "params": {}})
    assert plist.status_code == 200
    pnames = {p["name"] for p in plist.json()["result"]["prompts"]}
    assert "run_demo_overcharge_audit" in pnames
    assert "check_supplier_bill" in pnames

    # prompts/get returns ready-to-run message (not -32601)
    for name in ("run_demo_overcharge_audit", "check_supplier_bill", "match_monthly_bank_statement", "export_clean_spreadsheet"):
        pget = client.post("/mcp", json={"jsonrpc": "2.0", "id": 11, "method": "prompts/get", "params": {"name": name}})
        assert pget.status_code == 200
        body = pget.json()
        assert "error" not in body
        assert len(body["result"]["messages"]) >= 1
        assert body["result"]["messages"][0]["content"]["text"].strip()

    # Unknown prompt -> -32602
    bad_p = client.post("/mcp", json={"jsonrpc": "2.0", "id": 12, "method": "prompts/get", "params": {"name": "no_such_prompt"}})
    assert bad_p.json()["error"]["code"] == -32602

    # resources/read works for both schemaextract:// and billtally:// preset URIs
    rread = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 13, "method": "resources/read", "params": {"uri": "schemaextract://presets/cam_reconciliation_statement"}},
    )
    assert rread.status_code == 200
    rbody = rread.json()
    assert "error" not in rbody
    assert "Maplewood Commercial Property Management" in rbody["result"]["contents"][0]["text"]

    bad_r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 14, "method": "resources/read", "params": {"uri": "file:///etc/passwd"}},
    )
    assert bad_r.json()["error"]["code"] == -32602


def test_mcp_reconcile_raw_bank_csv_text(client: TestClient):
    bank_csv = (
        "Date,Description,Amount\n"
        "2026-10-03,ACH PAYMENT HEARTLAND FLOUR PANTRY SUPPLY,6928.00\n"
        "2026-10-05,ACH DEBIT VALLEY LINEN SERVICE,1250.00\n"
        "2026-10-06,ACH DEBIT VALLEY LINEN SERVICE RETRY,1250.00\n"
    )
    res = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 20,
            "method": "tools/call",
            "params": {
                "name": "reconcile_invoices_with_bank_ledger",
                "arguments": {
                    "invoices": [
                        {"invoice_number": "INV-1", "vendor": "Heartland Flour", "date": "2026-10-01", "total": 6928.00},
                        {"invoice_number": "INV-2", "vendor": "Valley Linen", "date": "2026-10-04", "total": 1250.00},
                    ],
                    "bank_csv_text": bank_csv,
                },
            },
        },
    )
    assert res.status_code == 200
    sc = res.json()["result"]["structuredContent"]
    assert sc["summary_metrics"]["matched_count"] == 2
    assert sc["summary_metrics"]["duplicate_count"] == 1


def test_mcp_audit_and_export_pack_compound_tool_and_xlsx_cover_seal(client: TestClient):
    raw_bill = (
        "Vendor: Oakridge Plumbing & Heating Services\n"
        "Invoice Number: INV-9914-B\n"
        "Issue Date: 2026-10-08\n"
        "1. Main Water Line Pipe | Qty: 10 | Unit Price: $100.00 | Amount: $1,000.00\n"
        "2. Emergency Labor | Qty: 2 | Unit Price: $150.00 | Amount: $500.00\n"
        "Subtotal: $1,500.00\n"
        "Tax: $0.00\n"
        "Total Due: $1,500.00\n"
    )
    res = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 30,
            "method": "tools/call",
            "params": {
                "name": "audit_and_export_pack",
                "arguments": {
                    "raw_text": raw_bill,
                    "bank_csv_text": "2026-10-09 OAKRIDGE PLUMBING $1,300.00\n",
                    "format": "xlsx",
                    "use_corrected_amounts": True,
                    "workspace_id": "test-compound-ws",
                },
            },
        },
    )
    assert res.status_code == 200
    result = res.json()["result"]
    assert result["isError"] is False
    sc = result["structuredContent"]
    assert sc["document"]["math_verified"] is False
    assert sc["document"]["discrepancy_delta"] == pytest.approx(200.0)
    audit_meta = sc["verified_audit_link"]
    assert audit_meta["audit_path"].startswith("/v/")
    assert audit_meta["audit_url"] in sc["document"]["vendor_dispute_note"]
    assert sc["reconciliation"]["summary_metrics"]["matched_count"] == 1

    # Download the generated .xlsx and verify Big-4 Audit Cover Sheet + preserved formulas
    dl_path = "/downloads/" + sc["export"]["filename"]
    dl_res = client.get(dl_path)
    assert dl_res.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(dl_res.content), data_only=False)
    ws = wb["Executive_Summary"]
    assert ws["J2"].value == "=ROUND(G2+H2,2)"
    all_col_a = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
    assert "VERIFIED BY BILLTALLY" in all_col_a
    assert "Verification URL" in all_col_a
    assert "Audit SHA-256" in all_col_a

    # Visit the minted /v/{audit_id} proof page
    v_res = client.get(audit_meta["audit_path"])
    assert v_res.status_code == 200
    assert "Oakridge Plumbing" in v_res.text
    assert audit_meta["sha256"] in v_res.text
    assert "@media print" in v_res.text


def test_verified_audit_link_xss_escaping_and_ttl_and_invalid_ids(client: TestClient):
    evil_doc = {
        "vendor": '<script>alert("xss")</script> Acme Co',
        "invoice_number": 'INV-<img src=x onerror=alert(1)>',
        "issue_date": "2026-11-01",
        "currency": "USD",
        "subtotal": 100.0,
        "tax": 0.0,
        "total": 120.0,
        "computed_total": 100.0,
        "discrepancy_delta": 20.0,
        "math_verified": False,
        "line_items": [{"description": "<b>Bad</b> item", "quantity": 1, "unit_price": 100.0, "amount": 120.0}],
    }
    post_res = client.post("/api/audit-link", json={"document": evil_doc})
    assert post_res.status_code == 200
    aid = post_res.json()["audit_id"]

    page = client.get(f"/v/{aid}")
    assert page.status_code == 200
    assert "<script>alert" not in page.text
    assert "&lt;script&gt;alert" in page.text
    assert "noindex, nofollow" in page.text

    # Invalid IDs return 404
    for bad in ("notvalid", "ZZZZZZZZZZZZ", "abc123"):
        assert client.get(f"/v/{bad}").status_code == 404

    # Expired audit link returns 404
    _AUDIT_STORE[aid]["expires_at"] = int(time.time()) - 10
    assert client.get(f"/v/{aid}").status_code == 404


def test_vertical_destination_pages_sitemap_robots_and_zero_reddit(client: TestClient):
    routes = [
        ("/convert/bank-statement-to-qbo-csv", "/?vertical=bank-statement-to-qbo-csv"),
        ("/check/supplier-invoice", "/?vertical=supplier-invoice"),
        ("/check/contractor-invoice", "/?vertical=contractor-invoice"),
        ("/check/cam-reconciliation", "/?vertical=cam-reconciliation"),
    ]
    for path, expected_cta in routes:
        res = client.get(path)
        assert res.status_code == 200, path
        body = res.text
        assert expected_cta in body
        assert '"@type": "SoftwareApplication"' in body
        assert '"@type": "FAQPage"' in body
        assert "reddit" not in body.lower()

    # Check2QBO cross-link on bank statement page
    bank_html = client.get("/convert/bank-statement-to-qbo-csv").text
    assert "exactbaseline.com/qbo-check-reconcile" in bank_html

    # Sitemap & robots
    sm = client.get("/sitemap.xml")
    assert sm.status_code == 200
    for path, _ in routes:
        assert path in sm.text

    rb = client.get("/robots.txt")
    assert rb.status_code == 200
    assert "Disallow: /v/" in rb.text
    assert "Disallow: /api/" in rb.text
    assert "Sitemap:" in rb.text

    # Main workbench includes Phase 2 privacy + wipe + audit link controls and zero Reddit text
    home = client.get("/").text
    assert 'id="privacy-mode-badge"' in home
    assert 'id="wipe-session-btn"' in home
    assert 'id="copy-audit-link-btn"' in home
    assert "/convert/bank-statement-to-qbo-csv" in home
    assert "/check/cam-reconciliation" in home
    assert "reddit" not in home.lower()


def test_edge_cases_malformed_audit_zero_total_fifo_eviction_dde_and_bank_csv(client: TestClient):
    from app.audit_links import MAX_AUDIT_LINKS, get_audit_record
    from app.exporter import export_ledger_bundle
    from app.mcp_compound import parse_raw_bank_csv_text
    from app.models import ExportBundleRequest

    # 1. Malformed /api/audit-link payloads never 500 on GET /v/{audit_id}
    assert client.post("/api/audit-link", content="not-json", headers={"content-type": "application/json"}).status_code == 400
    assert client.post("/api/audit-link", json={"missing": "doc"}).status_code == 400
    weird_res = client.post(
        "/api/audit-link",
        json={
            "document": {
                "vendor": "Weird Co",
                "total": "$1,200.00",
                "computed_total": 0.0,
                "discrepancy_delta": 1200.0,
                "math_verified": False,
                "line_items": "not-a-list",
            }
        },
    )
    assert weird_res.status_code == 200
    weird_page = client.get(weird_res.json()["audit_path"])
    assert weird_page.status_code == 200
    assert "$0.00" in weird_page.text
    assert "$1,200.00" in weird_page.text

    # Under-billed (delta < 0) renders banner-warn
    under_res = client.post(
        "/api/audit-link",
        json={"document": {"vendor": "Under Co", "currency": "EUR", "total": 90.0, "computed_total": 100.0, "discrepancy_delta": -10.0, "math_verified": False, "line_items": []}},
    )
    under_page = client.get(under_res.json()["audit_path"])
    assert under_page.status_code == 200
    assert "banner-warn" in under_page.text
    assert "EUR 90.00" in under_page.text

    # 2. FIFO eviction boundary (MAX_AUDIT_LINKS + 1)
    first_meta = create_audit_link({"vendor": "First Evicted"})
    for i in range(MAX_AUDIT_LINKS):
        create_audit_link({"vendor": f"Filler {i}"})
    assert get_audit_record(first_meta["audit_id"]) is None

    # 3. Multi-doc Excel Cover Sheet + DDE formula injection neutralization (including leading \n)
    dde_docs = [
        {"vendor": "=CMD|'/C calc'!A0", "invoice_number": "\n=1+1", "subtotal": 100.0, "tax": 0.0, "total": 100.0, "computed_subtotal": 100.0, "computed_total": 100.0, "math_verified": True, "line_items": []},
        {"vendor": "+2+2", "invoice_number": "@SUM(A1)", "subtotal": 200.0, "tax": 0.0, "total": 250.0, "computed_subtotal": 200.0, "computed_total": 200.0, "math_verified": False, "line_items": []},
    ]
    exp = export_ledger_bundle(ExportBundleRequest(documents=dde_docs, format="xlsx"), audit_url="=HYPERLINK()", audit_sha256="abc123")
    wb = openpyxl.load_workbook(io.BytesIO(client.get(exp.download_url).content), data_only=False)
    ws = wb["Executive_Summary"]
    assert ws["B2"].value.startswith("'=")
    assert ws["C2"].value.startswith("'\n=")
    assert ws["F4"].value == "TOTAL ALL BILLS"
    assert ws["G4"].value == "=SUM(G2:G3)"
    assert ws["A6"].value == "VERIFIED BY BILLTALLY"
    assert "Discrepancy flagged" in str(ws["B7"].value)
    assert str(ws["B8"].value).startswith("'=")

    # 4. Worst-case raw bank CSV parsing (quoted commas, TSV, parenthesized negatives, zero rows, empty)
    assert parse_raw_bank_csv_text("") == []
    assert parse_raw_bank_csv_text("Date,Description,Amount\n") == []
    quoted = parse_raw_bank_csv_text('Date,Description,Amount\n2026-10-03,"ACME, INC.","($1,250.00)"\n2026-10-04,ZERO,0.00\n2026-10-05,BAD,N/A\n')
    assert len(quoted) == 1 and quoted[0]["description"] == "ACME, INC." and quoted[0]["amount"] == pytest.approx(1250.0)
    tsv = parse_raw_bank_csv_text("Date\tDescription\tAmount\n2026-10-08\tMETRO ELECTRIC\t-$400.00\n")
    assert len(tsv) == 1 and tsv[0]["amount"] == pytest.approx(400.0)
    headerless_tsv = parse_raw_bank_csv_text("2026-10-08\tMETRO ELECTRIC\t$1,400.00\n2026-10-09\tVALLEY LINEN\t1250.00-\n")
    assert len(headerless_tsv) == 2
    assert headerless_tsv[0]["amount"] == pytest.approx(1400.0)
    assert headerless_tsv[1]["amount"] == pytest.approx(1250.0)

    # 5. Server-side integrity recomputation blocks spoofed math_verified=True + checks privacy headers & 128-bit ID
    spoof_res = client.post(
        "/api/audit-link",
        json={
            "document": {
                "vendor": "Spoof Co",
                "total": 999.0,
                "tax": 0.0,
                "math_verified": True,
                "line_items": [{"description": "Item", "quantity": 1, "unit_price": 100.0, "amount": 100.0}],
            }
        },
    )
    assert spoof_res.status_code == 200
    assert len(spoof_res.json()["audit_id"]) == 32
    spoof_page = client.get(spoof_res.json()["audit_path"])
    assert spoof_page.status_code == 200
    assert "Overcharge flagged" in spoof_page.text
    assert "no-store" in spoof_page.headers.get("cache-control", "")
    assert "noindex" in spoof_page.headers.get("x-robots-tag", "")
    assert spoof_page.headers.get("referrer-policy") == "no-referrer"

    # 6. JSON-RPC batch > 20 rejected & non-dict params returns -32602
    assert client.post("/mcp", json=[{"jsonrpc": "2.0", "id": i, "method": "ping"} for i in range(21)]).status_code == 400
    bad_params = client.post("/mcp", json={"jsonrpc": "2.0", "id": 99, "method": "tools/call", "params": []})
    assert bad_params.status_code == 200 and bad_params.json()["error"]["code"] == -32602

    # 7. audit_and_export_pack with use_corrected_amounts omitted reconciles against corrected total consistently
    raw_discrepant = (
        "Vendor: Oakridge Plumbing\nInvoice Number: INV-OMIT-1\nIssue Date: 2026-10-08\n"
        "1. Labor | Qty: 2 | Unit Price: $100.00 | Amount: $300.00\nSubtotal: $300.00\nTax: $0.00\nTotal Due: $300.00\n"
    )
    omit_res = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 100,
            "method": "tools/call",
            "params": {
                "name": "audit_and_export_pack",
                "arguments": {
                    "raw_text": raw_discrepant,
                    "bank_csv_text": "2026-10-09 OAKRIDGE PLUMBING $200.00\n",
                    "workspace_id": "test-omit-ws",
                },
            },
        },
    )
    assert omit_res.status_code == 200
    omit_sc = omit_res.json()["result"]["structuredContent"]
    assert omit_sc["reconciliation"]["summary_metrics"]["matched_count"] == 1

