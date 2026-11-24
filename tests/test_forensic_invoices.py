"""
20-Case Forensic Invoice Accounting Benchmark (`tests/test_forensic_invoices.py`, Cases 1-20).
Tests 20 diverse supplier, contractor, commercial CAM, SaaS, freight, legal, medical,
unstructured, zero-dollar, and DDE-injection invoices through live FastAPI endpoints.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List

from fastapi.testclient import TestClient
import openpyxl
import pytest

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def pro_api_key(client: TestClient) -> str:
    res = client.post("/api/quota/upgrade", params={"workspace_id": "forensic-20-inv-ws"})
    assert res.status_code == 200
    return res.json()["api_key"]


def _build_super_long_invoice() -> str:
    lines = [
        "Vendor: Apex Industrial MRO Supply Corp.",
        "Invoice Number: MRO-2026-7741",
        "Issue Date: 2026-10-15",
        "Due Date: 2026-11-14",
    ]
    for i in range(1, 81):
        qty = 2
        unit = 10.00 + (i % 5)
        amt = qty * unit
        if i == 73:
            amt += 0.37  # Buried $0.37 rounding overcharge on line 73
        lines.append(f"{i}. MRO Fastener Kit #{i:03d} | Qty: {qty} | Unit Price: ${unit:.2f} | Amount: ${amt:.2f}")
    lines.append("Subtotal: $1,920.37")
    lines.append("Tax: $0.00")
    lines.append("Total Due: $1,920.37")
    return "\n".join(lines)


INVOICE_CASES: List[Dict[str, Any]] = [
    {
        "id": 1,
        "name": "Wholesale Food Distributor (Balanced)",
        "raw_text": (
            "Vendor: Heartland Pantry Supply Co.\nInvoice Number: HP-1001\nIssue Date: 2026-10-01\nDue Date: 2026-10-31\n"
            "1. Organic Flour 50lb | Qty: 20 | Unit Price: $40.00 | Amount: $800.00\n"
            "2. Unsalted Butter Case | Qty: 10 | Unit Price: $120.00 | Amount: $1,200.00\n"
            "Subtotal: $2,000.00\nSales Tax (8.25%): $165.00\nTotal Due: $2,165.00\n"
        ),
        "total": 2165.00,
        "computed": 2165.00,
        "delta": 0.00,
        "verified": True,
    },
    {
        "id": 2,
        "name": "Plumbing Contractor (+$200 Overcharge)",
        "raw_text": (
            "Vendor: Oakridge Plumbing & Heating\nInvoice Number: OAK-442\nIssue Date: 2026-10-05\n"
            "1. Emergency Main Line Labor | Qty: 14 | Unit Price: $165.00 | Amount: $2,510.00\n"
            "2. Copper Valve Assembly | Qty: 2 | Unit Price: $95.00 | Amount: $190.00\n"
            "Subtotal: $2,700.00\nTax: $0.00\nTotal Due: $2,700.00\n"
        ),
        "total": 2700.00,
        "computed": 2500.00,
        "delta": 200.00,
        "verified": False,
        "expect_dispute": True,
    },
    {
        "id": 3,
        "name": "Electrical Contractor (-$100 Under-billed)",
        "raw_text": (
            "Vendor: Beacon Commercial Electric LLC\nInvoice Number: BCE-882\nIssue Date: 2026-10-06\n"
            "1. Panel Breaker Upgrade | Qty: 6 | Unit Price: $120.00 | Amount: $620.00\n"
            "Subtotal: $620.00\nTax: $0.00\nTotal Due: $620.00\n"
        ),
        "total": 620.00,
        "computed": 720.00,
        "delta": -100.00,
        "verified": False,
        "expect_dispute": True,
    },
    {
        "id": 4,
        "name": "Subtotal Addition Error (+$45)",
        "raw_text": (
            "Vendor: Midwest Linen Services\nInvoice Number: MLS-304\nIssue Date: 2026-10-07\n"
            "1. Kitchen Aprons | Qty: 50 | Unit Price: $2.00 | Amount: $100.00\n"
            "2. Table Linens | Qty: 40 | Unit Price: $5.00 | Amount: $200.00\n"
            "Subtotal: $345.00\nTax: $0.00\nTotal Due: $345.00\n"
        ),
        "total": 345.00,
        "computed": 300.00,
        "delta": 45.00,
        "verified": False,
        "expect_dispute": True,
    },
    {
        "id": 5,
        "name": "Unparenthesized Sales Tax Rate + Total Error",
        "raw_text": (
            "Vendor: Harbor Office Furnishings\nInvoice Number: HOF-511\nIssue Date: 10/08/2026\n"
            "1. Ergonomic Task Chair 4 x $250.00 = $1,000.00\n"
            "Subtotal: $1,000.00\nSales Tax 8.875%: $88.75\nAmount Due: $1,138.75\n"
        ),
        "total": 1138.75,
        "computed": 1088.75,
        "delta": 50.00,
        "verified": False,
        "expect_tax": 88.75,
        "expect_date": "2026-10-08",
    },
    {
        "id": 6,
        "name": "Offsetting Line Errors ($0.00 Net Delta)",
        "raw_text": (
            "Vendor: Summit Janitorial Co.\nInvoice Number: SJC-609\nIssue Date: 2026-10-09\n"
            "1. Nightly Floor Waxing | Qty: 5 | Unit Price: $100.00 | Amount: $550.00\n"
            "2. Window Cleaning | Qty: 4 | Unit Price: $100.00 | Amount: $350.00\n"
            "Subtotal: $900.00\nTax: $0.00\nTotal Due: $900.00\n"
        ),
        "total": 900.00,
        "computed": 900.00,
        "delta": 0.00,
        "verified": False,
        "forbid_summary_substr": "under-billed by $0.00",
    },
    {
        "id": 7,
        "name": "Super-Long 80-Line Invoice (Line 73 +$0.37)",
        "raw_text": _build_super_long_invoice(),
        "total": 1920.37,
        "computed": 1920.00,
        "delta": 0.37,
        "verified": False,
        "expect_lines": 80,
    },
    {
        "id": 8,
        "name": "Negative Credits & Parenthesized Memo",
        "raw_text": (
            "Vendor: Valley Beverage Distributors\nInvoice Number: VBD-902\nIssue Date: 2026-10-10\n"
            "| Description | Qty | Unit Price | Amount |\n"
            "| Craft Kegs | 10 | $150.00 | $1,500.00 |\n"
            "| Returned Pallet Credit | 1 | -$400.00 | -$400.00 |\n"
            "| Damaged Case Credit | 1 | ($125.50) | ($125.50) |\n"
            "Subtotal: $974.50\nTax: $0.00\nTotal Due: $974.50\n"
        ),
        "total": 974.50,
        "computed": 974.50,
        "delta": 0.00,
        "verified": True,
        "expect_lines": 3,
    },
    {
        "id": 9,
        "name": "Fractional Qty & Sub-Cent Unit Prices",
        "raw_text": (
            "Vendor: Precision Packaging Solutions\nInvoice Number: PPS-118\nIssue Date: 2026-10-11\n"
            "1. Custom Foil Pouches | Qty: 3500 | Unit Price: $0.0425 | Amount: $148.75\n"
            "2. Press Setup Labor | Qty: 12.5 | Unit Price: $142.50 | Amount: $1,781.25\n"
            "Subtotal: $1,930.00\nTax: $0.00\nTotal Due: $1,930.00\n"
        ),
        "total": 1930.00,
        "computed": 1930.00,
        "delta": 0.00,
        "verified": True,
    },
    {
        "id": 10,
        "name": "Duplicate Line Item Warning",
        "raw_text": (
            "Vendor: Metro Waste Management\nInvoice Number: MWM-204\nIssue Date: 2026-10-12\n"
            "1. Monthly Dumpster Service | Qty: 1 | Unit Price: $320.00 | Amount: $320.00\n"
            "2. Monthly Dumpster Service | Qty: 1 | Unit Price: $320.00 | Amount: $320.00\n"
            "Subtotal: $640.00\nTax: $0.00\nTotal Due: $640.00\n"
        ),
        "total": 640.00,
        "computed": 640.00,
        "delta": 0.00,
        "verified": True,
        "expect_dup_warning": True,
    },
    {
        "id": 11,
        "name": "High Effective Tax Rate (>12% Warning)",
        "raw_text": (
            "Vendor: Grand Convention Hotel\nInvoice Number: GCH-771\nIssue Date: 2026-10-13\n"
            "1. Conference Room Rental | Qty: 2 | Unit Price: $500.00 | Amount: $1,000.00\n"
            "Subtotal: $1,000.00\nTax: $165.00\nTotal Due: $1,165.00\n"
        ),
        "total": 1165.00,
        "computed": 1165.00,
        "delta": 0.00,
        "verified": True,
        "expect_high_tax": True,
    },
    {
        "id": 12,
        "name": "Commercial CAM/NNN Lease True-Up (+$350)",
        "raw_text": (
            "Vendor: Maplewood Commercial Property Management\nInvoice Number: CAM-2026-104\nIssue Date: 2026-10-14\n"
            "1. Annual Landscaping Share | Qty: 12 | Unit Price: $250.00 | Amount: $3,000.00\n"
            "2. Property Insurance Share | Qty: 12 | Unit Price: $300.00 | Amount: $3,950.00\n"
            "3. Monthly CAM Escrow Paid | Qty: 12 | Unit Price: -$500.00 | Amount: -$6,000.00\n"
            "Subtotal: $950.00\nTax: $0.00\nBalance Due: $950.00\n"
        ),
        "total": 950.00,
        "computed": 600.00,
        "delta": 350.00,
        "verified": False,
    },
    {
        "id": 13,
        "name": "SaaS Cloud Usage Invoice (US Dates, Net 30)",
        "raw_text": (
            "Vendor: CloudScale Infrastructure Inc.\nInvoice Number: CS-90812\n"
            "Invoice Date: 10/01/2026\nDue Date: 10/31/2026\n"
            "1. Enterprise Seats 25 x $40.00 = $1,000.00\n"
            "2. Compute Overage 100 units x $1.50 = $150.00\n"
            "3. SLA Outage Credit 1 ea x -$75.00 = -$75.00\n"
            "Subtotal: $1,075.00\nTax: $0.00\nAmount Due: $1,075.00\n"
        ),
        "total": 1075.00,
        "computed": 1075.00,
        "delta": 0.00,
        "verified": True,
        "expect_date": "2026-10-01",
    },
    {
        "id": 14,
        "name": "Freight & Logistics BOL (UOMs + Balance Due)",
        "raw_text": (
            "Vendor: Heartland Freight Logistics\nInvoice Number: BOL-5541\nDate: 10/16/2026\n"
            "1. Linehaul Freight 2000 lbs x $0.45 = $900.00\n"
            "2. Dock Detention 3 hrs x $85.00 = $255.00\n"
            "3. Liftgate Delivery 1 ea x $95.00 = $95.00\n"
            "Subtotal: $1,250.00\nTax: $0.00\nBalance Due: $1,250.00\n"
        ),
        "total": 1250.00,
        "computed": 1250.00,
        "delta": 0.00,
        "verified": True,
        "expect_lines": 3,
    },
    {
        "id": 15,
        "name": "Legal Retainer Invoice (0.25h + Net Payable)",
        "raw_text": (
            "Vendor: Vance & Sterling LLP\nInvoice Number: VS-2026-88\nIssue Date: 2026-10-17\n"
            "1. Contract Review Partner 2.75 hrs x $400.00 = $1,100.00\n"
            "2. Associate Filing Prep 1.25 hrs x $240.00 = $300.00\n"
            "3. Trust Retainer Applied 1 ea x -$500.00 = -$500.00\n"
            "Subtotal: $900.00\nTax: $0.00\nNet Payable: $900.00\n"
        ),
        "total": 900.00,
        "computed": 900.00,
        "delta": 0.00,
        "verified": True,
    },
    {
        "id": 16,
        "name": "European Medical Supply Invoice (EUR)",
        "raw_text": (
            "Vendor: MedTech GmbH\nInvoice Number: MT-EU-441\nIssue Date: 2026-10-18\nCurrency: EUR\n"
            "1. Sterile Gloves Box | Qty: 20 | Unit Price: €12.50 | Amount: €250.00\n"
            "2. N95 Respirators | Qty: 10 | Unit Price: €30.00 | Amount: €350.00\n"
            "Subtotal: €600.00\nTax: €0.00\nTotal Due: €600.00\n"
        ),
        "total": 600.00,
        "computed": 550.00,
        "delta": 50.00,
        "verified": False,
        "expect_currency": "EUR",
    },
    {
        "id": 17,
        "name": "Header-Trap Table ('Total\\n1.' Guard)",
        "raw_text": (
            "Vendor: Northstar Printing Press\nInvoice Number: NPP-109\nDate: 10/19/2026\n"
            "Description   Qty   Price   Total\n"
            "1. Color Brochures 500 x $0.80 = $400.00\n"
            "2. Mailing Envelopes 200 x $0.25 = $50.00\n"
            "Subtotal: $450.00\nTax: $36.00\nInvoice Total: $486.00\n"
        ),
        "total": 486.00,
        "computed": 486.00,
        "delta": 0.00,
        "verified": True,
    },
    {
        "id": 18,
        "name": "Unstructured Freeform Bill (Manual Review)",
        "raw_text": (
            "Vendor: Mystery Consulting Group\nInvoice Number: MCG-001\nDate: 10/20/2026\n"
            "Thank you for your business. Please remit $1,450.00 for Q3 advisory services.\n"
            "Amount Due: $1,450.00\n"
        ),
        "total": 1450.00,
        "computed": 1450.00,
        "delta": 0.00,
        "verified": False,
        "expect_manual_review": True,
    },
    {
        "id": 19,
        "name": "Zero-Dollar 100% Credited Invoice",
        "raw_text": (
            "Vendor: CloudDesk Software\nInvoice Number: CD-ZERO-1\nIssue Date: 2026-10-21\n"
            "1. Pro Plan Monthly | Qty: 1 | Unit Price: $99.00 | Amount: $99.00\n"
            "2. Launch Promo Credit | Qty: 1 | Unit Price: -$99.00 | Amount: -$99.00\n"
            "Subtotal: $0.00\nTax: $0.00\nTotal Due: $0.00\n"
        ),
        "total": 0.00,
        "computed": 0.00,
        "delta": 0.00,
        "verified": True,
    },
    {
        "id": 20,
        "name": "DDE Formula-Injection Adversarial Invoice",
        "raw_text": (
            "Vendor: =CMD|'/C calc'!A0\nInvoice Number: +DDE-2026\nIssue Date: 2026-10-22\n"
            "1. +SUM(A1:A9) Consulting | Qty: 2 | Unit Price: $150.00 | Amount: $300.00\n"
            "Subtotal: $300.00\nTax: $0.00\nTotal Due: $300.00\n"
        ),
        "total": 300.00,
        "computed": 300.00,
        "delta": 0.00,
        "verified": True,
        "check_dde_export": True,
    },
]


@pytest.mark.parametrize("case", INVOICE_CASES, ids=[f"case_{c['id']:02d}_{c['name']}" for c in INVOICE_CASES])
def test_forensic_20_invoices(client: TestClient, pro_api_key: str, case: Dict[str, Any]):
    res = client.post(
        "/api/extract",
        json={"raw_text": case["raw_text"], "api_key": pro_api_key, "workspace_id": "forensic-20-inv-ws"},
    )
    assert res.status_code == 200, f"Case {case['id']} failed HTTP {res.status_code}: {res.text}"
    d = res.json()

    assert d["total"] == pytest.approx(case["total"])
    assert d["computed_total"] == pytest.approx(case["computed"])
    assert d["discrepancy_delta"] == pytest.approx(case["delta"])
    assert d["math_verified"] is case["verified"]

    if "expect_tax" in case:
        assert d["tax"] == pytest.approx(case["expect_tax"])
    if "expect_date" in case:
        assert d["issue_date"] == case["expect_date"]
    if "expect_lines" in case:
        assert len(d["line_items"]) == case["expect_lines"]
    if "expect_currency" in case:
        assert d["currency"] == case["expect_currency"]
    if case.get("expect_dispute"):
        assert d["vendor_dispute_note"] and len(d["vendor_dispute_note"]) > 30
    if case.get("expect_dup_warning"):
        assert d["duplicate_line_items_warning"] is not None
    if case.get("expect_high_tax"):
        assert d["high_tax_rate_warning"] is not None
    if case.get("expect_manual_review"):
        assert "Manual review required" in d["plain_english_summary"]
        assert d["vendor_dispute_note"] is None
    if "forbid_summary_substr" in case:
        assert case["forbid_summary_substr"] not in d["plain_english_summary"]
    if case.get("check_dde_export"):
        exp = client.post("/api/export", json={"documents": [d], "format": "xlsx", "api_key": pro_api_key})
        assert exp.status_code == 200
        dl = client.get(exp.json()["download_url"])
        assert dl.status_code == 200
        wb = openpyxl.load_workbook(io.BytesIO(dl.content), data_only=False)
        assert str(wb["Executive_Summary"]["B2"].value).startswith("'=")
        assert not str(wb["Executive_Summary"]["C2"].value).startswith(("=", "+", "-", "@"))
        assert str(wb["Normalized_Line_Items"]["F2"].value).startswith("'+")
