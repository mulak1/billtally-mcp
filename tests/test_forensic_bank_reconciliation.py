"""
10-Case Forensic Bank Statement & Reconciliation Benchmark (`tests/test_forensic_bank_reconciliation.py`, Cases 21-30).
Tests Chase, Bank of America, Wells Fargo, Credit Union Debit/Credit, Titled TSV, Colliding Headers,
Details-only fallback, Debit+Refund pairs, True Duplicate ACH, Distinct 1-to-1 Invoices, and 250-Row Statements
through live FastAPI endpoints with per-case isolation.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi.testclient import TestClient
import pytest

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def pro_api_key(client: TestClient) -> str:
    res = client.post("/api/quota/upgrade", params={"workspace_id": "forensic-10-bank-ws"})
    assert res.status_code == 200
    return res.json()["api_key"]


def _build_250_row_statement() -> str:
    rows = ["Date,Description,Amount"]
    for i in range(1, 251):
        day = ((i - 1) % 28) + 1
        if i == 1:
            rows.append(f'03/{day:02d}/2026,"=CMD|calc, INC.","($75.00)"')
        elif i == 2:
            rows.append(f"03/{day:02d}/2026,WHOLE DOLLAR DEPOSIT,$500")
        else:
            rows.append(f'03/{day:02d}/2026,"VENDOR #{i}, LLC",-{10 + (i % 90)}.25')
    return "\n".join(rows)


BANK_CSV_CASES: List[Dict[str, Any]] = [
    {
        "id": 21,
        "name": "Chase Business Checking CSV (Details vs Description)",
        "csv": (
            "Details,Posting Date,Description,Amount,Type,Balance\n"
            "DEBIT,03/15/2026,HEARTLAND PANTRY SUPPLY,-692.80,ACH_DEBIT,14307.20\n"
            "CREDIT,03/16/2026,STRIPE PAYOUT,2450.00,ACH_CREDIT,16757.20\n"
        ),
        "rows": 2,
        "must_contain": ["03/15/2026,HEARTLAND PANTRY SUPPLY,-692.80", "03/16/2026,STRIPE PAYOUT,2450.00"],
        "must_not_contain": [],
    },
    {
        "id": 22,
        "name": "Bank of America Multi-Line Summary + Running Bal",
        "csv": (
            "Description,,Summary Amt.\n"
            "Beginning balance as of 03/01/2026,,12500.00\n"
            "Total credits,,1500.00\n"
            "Date,Description,Amount,Running Bal.\n"
            "03/10/2026,OAKRIDGE PLUMBING,-450.00,12050.00\n"
            "03/12/2026,CLIENT WIRE DEPOSIT,1500.00,13550.00\n"
        ),
        "rows": 2,
        "must_contain": ["03/10/2026,OAKRIDGE PLUMBING,-450.00"],
        "must_not_contain": ["12050.00"],
    },
    {
        "id": 23,
        "name": "Wells Fargo Headerless CSV",
        "csv": '"03/15/2026","-450.00","*","","ACME PLUMBING SERVICES"\n"03/16/2026","1200.00","*","","SQUARE DEPOSIT"\n',
        "rows": 2,
        "must_contain": ["03/15/2026,ACME PLUMBING SERVICES,-450.00", "03/16/2026,SQUARE DEPOSIT,1200.00"],
        "must_not_contain": [],
    },
    {
        "id": 24,
        "name": "Credit Union Separate Debit & Credit Columns",
        "csv": (
            "Date,Description,Debit,Credit,Balance\n"
            "03/18/2026,VALLEY LINEN SERVICE,325.00,,9675.00\n"
            "03/19/2026,MERCHANT SETTLEMENT,,840.50,10515.50\n"
        ),
        "rows": 2,
        "must_contain": ["03/18/2026,VALLEY LINEN SERVICE,-325.00", "03/19/2026,MERCHANT SETTLEMENT,840.50"],
        "must_not_contain": [],
    },
    {
        "id": 25,
        "name": "2-Line Titled Tab-Separated (TSV) Statement",
        "csv": (
            "First Regional Business Checking\n"
            "Statement Period: March 2026\n"
            "Date\tDescription\tAmount\tRunning Bal.\n"
            "03/20/2026\tAPEX INDUSTRIAL SUPPLY\t-810.25\t9189.75\n"
        ),
        "rows": 1,
        "must_contain": ["03/20/2026,APEX INDUSTRIAL SUPPLY,-810.25"],
        "must_not_contain": ["9189.75"],
    },
    {
        "id": 26,
        "name": "Colliding Headers (Payment Date, Charge Description, Credit Memo)",
        "csv": (
            "Payment Date,Charge Description,Credit Memo,Amount\n"
            "03/21/2026,Check #1042 HARBOR OFFICE,Ref 99,-175.00\n"
        ),
        "rows": 1,
        "must_contain": ["03/21/2026,Check #1042 HARBOR OFFICE,-175.00"],
        "must_not_contain": [],
    },
    {
        "id": 30,
        "name": "250-Row Monthly Statement (Quoted Commas, Whole Dollars, DDE)",
        "csv": _build_250_row_statement(),
        "rows": 250,
        "must_contain": ['03/01/2026,"\'=CMD|calc, INC.",-75.00', "03/02/2026,WHOLE DOLLAR DEPOSIT,500.00"],
        "must_not_contain": [],
    },
    {
        "id": 31,
        "name": "Details-Only Fallback Header (No Primary Description Column)",
        "csv": "Date,Details,Amount\n03/22/2026,NORTHSTAR PRINTING,-180.00\n",
        "rows": 1,
        "must_contain": ["03/22/2026,NORTHSTAR PRINTING,-180.00"],
        "must_not_contain": [],
    },
]


@pytest.mark.parametrize("case", BANK_CSV_CASES, ids=[f"case_{c['id']:02d}_{c['name']}" for c in BANK_CSV_CASES])
def test_forensic_bank_csv_exports(client: TestClient, pro_api_key: str, case: Dict[str, Any]):
    res = client.post("/api/bank-csv-export", json={"bank_csv_text": case["csv"], "api_key": pro_api_key})
    assert res.status_code == 200 and res.json()["row_count"] == case["rows"]
    dl = client.get(res.json()["download_url"]).text
    for expected in case["must_contain"]:
        assert expected in dl
    for forbidden in case["must_not_contain"]:
        assert forbidden not in dl


def test_case_27_debit_and_refund_pair_no_false_duplicate(client: TestClient):
    res = client.post(
        "/api/reconcile",
        json={
            "invoices": [{"invoice_number": "INV-REF-1", "vendor": "CloudScale", "date": "03/16/2026", "total": 89.99}],
            "bank_transactions": [
                {"txn_id": "T-DEBIT", "date": "03/15/2026", "description": "CLOUDSCALE HOSTING", "amount": -89.99},
                {"txn_id": "T-REFUND", "date": "03/16/2026", "description": "CLOUDSCALE REFUND", "amount": 89.99},
            ],
        },
    )
    assert res.status_code == 200
    rep = res.json()
    assert rep["summary_metrics"]["duplicate_count"] == 0
    assert rep["matched"][0]["bank_txn_id"] == "T-DEBIT"


def test_case_28_true_duplicate_ach_debit_caught(client: TestClient):
    res = client.post(
        "/api/reconcile",
        json={
            "invoices": [{"invoice_number": "INV-DUP-1", "vendor": "Valley Linen", "date": "03/10/2026", "total": 1250.00}],
            "bank_transactions": [
                {"txn_id": "T-1", "date": "03/11/2026", "description": "ACH VALLEY LINEN", "amount": -1250.00},
                {"txn_id": "T-2", "date": "03/13/2026", "description": "ACH VALLEY LINEN RETRY", "amount": -1250.00},
            ],
        },
    )
    assert res.status_code == 200
    rep = res.json()
    assert rep["summary_metrics"]["matched_count"] == 1
    assert rep["summary_metrics"]["duplicate_count"] == 1
    assert rep["unmatched_bank_txns"][0]["status"] == "DUPLICATE_DEBIT_ALERT"


def test_case_29_two_distinct_same_amount_invoices_no_false_duplicate(client: TestClient):
    res = client.post(
        "/api/reconcile",
        json={
            "invoices": [
                {"invoice_number": "INV-A", "vendor": "Heartland Flour", "date": "03/01/2026", "total": 500.00},
                {"invoice_number": "INV-B", "vendor": "Heartland Flour", "date": "03/04/2026", "total": 500.00},
            ],
            "bank_transactions": [
                {"txn_id": "T-A", "date": "03/02/2026", "description": "HEARTLAND FLOUR", "amount": -500.00},
                {"txn_id": "T-B", "date": "03/05/2026", "description": "HEARTLAND FLOUR", "amount": -500.00},
            ],
        },
    )
    assert res.status_code == 200
    rep = res.json()
    assert rep["summary_metrics"]["matched_count"] == 2
    assert rep["summary_metrics"]["duplicate_count"] == 0
    assert rep["reconciliation_balanced"] is True
