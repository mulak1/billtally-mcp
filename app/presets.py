"""
Plain-English Small Business & Bookkeeping Sample Templates.
Free of developer jargon, AI/cloud buzzwords, em-dashes, or third-party vendor brand names.
All presets return deep copies to guarantee immutability.
"""

import copy
from typing import Any, Dict, List

_PRESETS: Dict[str, Dict[str, Any]] = {
    "messy_saas_invoice": {
        "id": "messy_saas_invoice",
        "title": "Wholesale Bakery & Kitchen Supply Bill ($6,928.00, Math Balances)",
        "badge": "Balanced to the penny · 5 items",
        "document_type": "invoice",
        "category": "Cost of Goods Sold: Food & Pantry",
        "description": "Weekly delivery bill for flour, butter, vanilla, refrigerated delivery, and a returned pallet credit.",
        "raw_text": (
            "INVOICE STATEMENT: HEARTLAND FLOUR & PANTRY SUPPLY CO.\n"
            "Vendor: Heartland Flour & Pantry Supply Co.\n"
            "Invoice Number: INV-2026-0842\n"
            "Issue Date: 2026-10-01\n"
            "Due Date: 2026-10-31\n"
            "Currency: USD\n"
            "------------------------------------------------------------------------\n"
            "1. 50-lb Sacks Unbleached Artisan Bread Flour | Qty: 40 | Unit Price: $125.00 | Amount: $5,000.00\n"
            "2. Cases Unsalted Creamery Pastry Butter (36 lbs) | Qty: 15 | Unit Price: $40.00 | Amount: $600.00\n"
            "3. Pure Madagascar Vanilla Bean Extract (Gallon) | Qty: 2 | Unit Price: $175.00 | Amount: $350.00\n"
            "4. Scheduled Refrigerated Morning Delivery & Liftgate | Qty: 1 | Unit Price: $850.00 | Amount: $850.00\n"
            "5. Returned Wooden Pallet Deposit Credit | Qty: 1 | Unit Price: -$400.00 | Amount: -$400.00\n"
            "------------------------------------------------------------------------\n"
            "Subtotal: $6,400.00\n"
            "Tax (8.25%): $528.00\n"
            "Total Due: $6,928.00\n"
        ),
    },
    "discrepant_contractor_invoice": {
        "id": "discrepant_contractor_invoice",
        "title": "Plumbing & Water Heater Repair Bill (+$200.00 Overcharge Caught)",
        "badge": "Math error caught · $200.00 overcharge",
        "document_type": "invoice",
        "category": "Repairs & Building Maintenance",
        "description": "Emergency plumbing bill where Line 3 (14 hours at $165/hr = $2,310.00) is typed as $2,510.00, adding $200.00 by mistake.",
        "raw_text": (
            "SERVICE & REPAIR BILLING\n"
            "Vendor: Oakridge Plumbing & Heating Services\n"
            "Invoice Number: INV-9914-B\n"
            "Issue Date: 2026-10-08\n"
            "Due Date: 2026-11-07\n"
            "Currency: USD\n"
            "------------------------------------------------------------------------\n"
            "1. Main Water Line Copper Pipe Replacement (Hours) | Qty: 12 | Unit Price: $185.00 | Amount: $2,220.00\n"
            "2. Commercial Hot Water Tank Pressure Valve Assembly | Qty: 1 | Unit Price: $1,450.00 | Amount: $1,450.00\n"
            "3. After-Hours Master Plumber Labor | Qty: 14 | Unit Price: $165.00 | Amount: $2,510.00\n"
            "4. Braided Stainless Supply Lines & Brass Fittings | Qty: 6 | Unit Price: $55.00 | Amount: $330.00\n"
            "------------------------------------------------------------------------\n"
            "Subtotal: $6,510.00\n"
            "Tax: $195.30\n"
            "Total Due: $6,705.30\n"
        ),
    },
    "bank_reconciliation_batch": {
        "id": "bank_reconciliation_batch",
        "title": "October Checking Statement vs. Supplier Bills (Duplicate Charge Caught)",
        "badge": "3 matched · 1 unpaid · 1 duplicate charge",
        "document_type": "bank_statement",
        "category": "Monthly Bank Statement Check",
        "description": "Matches 4 October supplier bills against 5 checking account withdrawals to spot a double-charged linen bill and a missing hardware store receipt.",
        "raw_text": (
            "MONTHLY CHECKING STATEMENT: OCTOBER 2026 OPERATING ACCOUNT\n"
            "Vendor: First Community Business Bank\n"
            "Invoice Number: STMT-2026-10\n"
            "Issue Date: 2026-10-31\n"
            "Currency: USD\n"
            "1. ACH PAYMENT HEARTLAND FLOUR & PANTRY SUPPLY | Qty: 1 | Unit Price: $6,928.00 | Amount: $6,928.00\n"
            "2. CHECK DEBIT VALLEY LINEN & APRON SERVICE | Qty: 1 | Unit Price: $1,250.00 | Amount: $1,250.00\n"
            "3. CHECK DEBIT VALLEY LINEN & APRON SERVICE RETRY | Qty: 1 | Unit Price: $1,250.00 | Amount: $1,250.00\n"
            "4. AUTO DEBIT MUNICIPAL WATER & POWER UTILITY | Qty: 1 | Unit Price: $540.00 | Amount: $540.00\n"
            "5. DEBIT CARD CORNER HARDWARE & PAINT STORE | Qty: 1 | Unit Price: $189.00 | Amount: $189.00\n"
            "Subtotal: $10,157.00\n"
            "Tax: $0.00\n"
            "Total: $10,157.00\n"
        ),
        "invoices": [
            {
                "invoice_number": "INV-2026-0842",
                "vendor": "Heartland Flour & Pantry Supply Co.",
                "date": "2026-10-01",
                "total": 6928.00,
                "currency": "USD",
            },
            {
                "invoice_number": "INV-VL-7731",
                "vendor": "Valley Linen & Apron Service",
                "date": "2026-10-04",
                "total": 1250.00,
                "currency": "USD",
            },
            {
                "invoice_number": "INV-UTIL-309",
                "vendor": "Municipal Water & Power Utility",
                "date": "2026-10-11",
                "total": 540.00,
                "currency": "USD",
            },
            {
                "invoice_number": "INV-2026-0912",
                "vendor": "Greenway Grounds & Snow Care",
                "date": "2026-10-25",
                "total": 3420.00,
                "currency": "USD",
            },
        ],
        "bank_transactions": [
            {
                "txn_id": "CHK-9001",
                "date": "2026-10-03",
                "description": "ACH PAYMENT HEARTLAND FLOUR PANTRY SUPPLY CO",
                "amount": 6928.00,
                "currency": "USD",
            },
            {
                "txn_id": "CHK-9002",
                "date": "2026-10-05",
                "description": "ACH DEBIT VALLEY LINEN APRON SERVICE",
                "amount": 1250.00,
                "currency": "USD",
            },
            {
                "txn_id": "CHK-9003",
                "date": "2026-10-06",
                "description": "ACH DEBIT VALLEY LINEN APRON SERVICE DUPLICATE",
                "amount": 1250.00,
                "currency": "USD",
            },
            {
                "txn_id": "CHK-9004",
                "date": "2026-10-12",
                "description": "AUTO DEBIT MUNICIPAL WATER POWER UTILITY",
                "amount": 540.00,
                "currency": "USD",
            },
            {
                "txn_id": "CHK-9005",
                "date": "2026-10-19",
                "description": "DEBIT CARD CORNER HARDWARE PAINT STORE",
                "amount": 189.00,
                "currency": "USD",
            },
        ],
    },
}

_ALIASES = {
    "wholesale_bakery_invoice": "messy_saas_invoice",
    "plumbing_repair_invoice": "discrepant_contractor_invoice",
}


def get_all_presets() -> List[Dict[str, Any]]:
    """Return a deep copy of all presets so callers cannot mutate internal state."""
    return [copy.deepcopy(v) for v in _PRESETS.values()]


def get_preset_by_id(preset_id: str) -> Dict[str, Any]:
    """Return a deep copy of a single preset by ID or raise KeyError."""
    resolved = _ALIASES.get(preset_id, preset_id)
    if resolved not in _PRESETS:
        raise KeyError(f"Unknown preset_id: {preset_id}")
    return copy.deepcopy(_PRESETS[resolved])
