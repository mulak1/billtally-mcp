"""
Invoice-to-Bank-Ledger Reconciliation Engine (`reconcile_invoices_with_bank_ledger`).
Cross-matches extracted invoices/receipts against bank statement transactions using
exact fixed-decimal (`Decimal`) arithmetic, currency equality, settlement date tolerance,
vendor token-overlap similarity, and duplicate charge detection.
"""

import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Set, Tuple

from app.extractor import _to_dec
from app.models import ReconcileLedgerRequest, ReconciliationReport

_CENT = Decimal("0.01")
_STOP_WORDS = {
    "inc", "llc", "corp", "ltd", "ab", "co", "ach", "debit", "wire", "out",
    "card", "charge", "the", "pos", "purchase", "payment", "checkcard",
    "autopay", "recurring", "online", "transfer", "bill", "pay", "pmt",
    "withdrawal", "dbt", "crd", "visa", "mastercard", "amex", "check", "chk",
}
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%m-%d-%Y",
    "%Y/%m/%d",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d-%b-%Y",
)


def _parse_date_opt(val: Any) -> date | None:
    text = str(val or "").strip()
    if not text:
        return None
    # Strip trailing time component if ISO timestamp (e.g. 2026-03-15T12:00:00Z)
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        text_iso = text[:10]
        try:
            return datetime.strptime(text_iso, "%Y-%m-%d").date()
        except ValueError:
            pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_iso_date(val: Any) -> date:
    parsed = _parse_date_opt(val)
    return parsed if parsed is not None else date(2026, 10, 1)


def _norm_currency(val: Any, fallback: str = "USD") -> str:
    c = str(val or fallback).strip().upper()
    return c if c else fallback


def _vendor_tokens(text: str) -> Set[str]:
    words = re.findall(r"[a-z0-9]{2,}", text.lower())
    return {w for w in words if w not in _STOP_WORDS}


def _vendor_similarity(vendor: str, bank_desc: str) -> float:
    v_tok = _vendor_tokens(vendor)
    b_tok = _vendor_tokens(bank_desc)
    if not v_tok or not b_tok:
        return 0.0
    overlap = len(v_tok & b_tok)
    return round(overlap / max(1, min(len(v_tok), len(b_tok))), 2)


def _detect_duplicate_bank_charges(
    bank_transactions: List[Dict[str, Any]],
    matched_indices: Set[int] | None = None,
) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """Identify duplicate bank debits having the same normalized vendor token, currency, sign, and amount within 5 days."""
    duplicates: List[Dict[str, Any]] = []
    duplicate_txn_ids: Set[str] = set()
    matched_set = matched_indices or set()
    seen: List[Tuple[Set[str], Decimal, str, date | None, Dict[str, Any], int]] = []

    for idx, txn in enumerate(bank_transactions):
        txn_id = str(txn.get("txn_id", f"TXN-{idx+1}"))
        amt = _to_dec(txn.get("amount", 0))
        curr = _norm_currency(txn.get("currency"), "USD")
        dt = _parse_date_opt(txn.get("date"))
        tokens = _vendor_tokens(str(txn.get("description", "")))

        is_dup_of = None
        is_dup_days = 0
        for prev_tokens, prev_amt, prev_curr, prev_dt, prev_txn, prev_idx in seen:
            # Skip if both transactions were legitimately matched 1-to-1 to distinct invoices
            if idx in matched_set and prev_idx in matched_set:
                continue
            # Opposite signs (e.g. debit -$100 and refund +$100) are not duplicate charges
            if (amt < Decimal("0.00")) != (prev_amt < Decimal("0.00")):
                continue
            same_amt = abs(abs(amt) - abs(prev_amt)) <= _CENT
            same_curr = curr == prev_curr
            if dt is not None and prev_dt is not None:
                days_apart = abs((dt - prev_dt).days)
                close_date = days_apart <= 5
            else:
                days_apart = 0
                close_date = False
            shared_vendor = len(tokens & prev_tokens) >= 1
            if same_amt and same_curr and close_date and shared_vendor:
                is_dup_of = prev_txn
                is_dup_days = days_apart
                break

        if is_dup_of is not None:
            duplicate_txn_ids.add(txn_id)
            duplicates.append(
                {
                    "duplicate_txn_id": txn_id,
                    "original_txn_id": str(is_dup_of.get("txn_id", "UNKNOWN")),
                    "date": str(dt or txn.get("date", "")),
                    "description": str(txn.get("description", "")),
                    "amount": float(abs(amt)),
                    "currency": curr,
                    "reason": (
                        f"Duplicate bank charge of {abs(amt):.2f} within "
                        f"{is_dup_days} day(s) of {is_dup_of.get('txn_id')}."
                    ),
                }
            )
        else:
            seen.append((tokens, amt, curr, dt, txn, idx))

    return duplicates, duplicate_txn_ids


def reconcile_invoices_with_bank_ledger(req: ReconcileLedgerRequest) -> ReconciliationReport:
    """
    Cross-match extracted invoices against bank statement transactions using pure Decimal tolerances.
    Returns a new immutable `ReconciliationReport`.
    """
    matched: List[Dict[str, Any]] = []
    unmatched_invoices: List[Dict[str, Any]] = []
    used_bank_indices: Set[int] = set()
    tol_dec = _to_dec(req.amount_tolerance)

    has_signed_debits = any(_to_dec(t.get("amount", 0)) < Decimal("0.00") for t in req.bank_transactions)
    for inv in req.invoices:
        inv_num = str(inv.get("invoice_number", "INV-UNKNOWN"))
        inv_vendor = str(inv.get("vendor", "Unknown Vendor"))
        inv_amt = _to_dec(inv.get("total", inv.get("amount", 0)))
        inv_date = _parse_iso_date(inv.get("date", inv.get("issue_date", "2026-10-01")))
        inv_curr = _norm_currency(inv.get("currency"), "USD")

        best_idx = None
        best_score = Decimal("-1")
        best_days = 999

        for b_idx, txn in enumerate(req.bank_transactions):
            if b_idx in used_bank_indices:
                continue
            txn_curr = _norm_currency(txn.get("currency"), inv_curr)
            if txn_curr != inv_curr:
                continue

            txn_amt = _to_dec(txn.get("amount", 0))
            amt_diff = abs(abs(inv_amt) - abs(txn_amt)) if inv_amt >= Decimal("0.00") else abs(inv_amt - txn_amt)
            if amt_diff > tol_dec:
                continue

            txn_date = _parse_iso_date(txn.get("date", "2026-10-01"))
            days_delta = abs((txn_date - inv_date).days)
            if days_delta > req.date_tolerance_days:
                continue

            sim = _vendor_similarity(inv_vendor, str(txn.get("description", "")))
            if sim <= 0.0:
                continue

            polarity_bonus = Decimal("50") if (has_signed_debits and inv_amt > Decimal("0.00") and txn_amt < Decimal("0.00")) else Decimal("0")
            score = Decimal(str(sim)) * Decimal("100") + polarity_bonus - Decimal(days_delta) - (amt_diff * Decimal("10"))
            if score > best_score:
                best_score = score
                best_idx = b_idx
                best_days = days_delta

        if best_idx is not None:
            used_bank_indices.add(best_idx)
            matched_txn = req.bank_transactions[best_idx]
            bank_amt_dec = _to_dec(matched_txn.get("amount", 0))
            matched.append(
                {
                    "invoice_number": inv_num,
                    "vendor": inv_vendor,
                    "invoice_date": str(inv_date),
                    "bank_txn_id": str(matched_txn.get("txn_id", f"TXN-{best_idx+1}")),
                    "bank_date": str(matched_txn.get("date", "")),
                    "bank_description": str(matched_txn.get("description", "")),
                    "invoice_amount": float(inv_amt),
                    "bank_amount": float(bank_amt_dec),
                    "currency": inv_curr,
                    "settlement_lag_days": best_days,
                    "match_confidence": round(
                        min(0.99, 0.85 + 0.14 * _vendor_similarity(inv_vendor, str(matched_txn.get("description", "")))),
                        2,
                    ),
                }
            )
        else:
            unmatched_invoices.append(
                {
                    "invoice_number": inv_num,
                    "vendor": inv_vendor,
                    "date": str(inv_date),
                    "total": float(inv_amt),
                    "currency": inv_curr,
                    "status": "UNMATCHED_INVOICE_ACCRUAL_PENDING",
                }
            )

    duplicate_charges, duplicate_txn_ids = _detect_duplicate_bank_charges(
        req.bank_transactions,
        matched_indices=used_bank_indices,
    )

    unmatched_bank_txns: List[Dict[str, Any]] = []
    for b_idx, txn in enumerate(req.bank_transactions):
        if b_idx in used_bank_indices:
            continue
        txn_id = str(txn.get("txn_id", f"TXN-{b_idx+1}"))
        status = "DUPLICATE_DEBIT_ALERT" if txn_id in duplicate_txn_ids else "UNRECEIPTED_BANK_DEBIT"
        amt_dec = _to_dec(txn.get("amount", 0))
        parsed_dt = _parse_date_opt(txn.get("date"))
        unmatched_bank_txns.append(
            {
                "txn_id": txn_id,
                "date": str(parsed_dt) if parsed_dt else str(txn.get("date", "")),
                "description": str(txn.get("description", "")),
                "amount": float(amt_dec),
                "currency": _norm_currency(txn.get("currency"), "USD"),
                "status": status,
            }
        )

    matched_volume = float(sum((abs(_to_dec(m["bank_amount"])) for m in matched), Decimal("0.00")).quantize(_CENT, rounding=ROUND_HALF_UP))
    unmatched_inv_volume = float(sum((abs(_to_dec(u["total"])) for u in unmatched_invoices), Decimal("0.00")).quantize(_CENT, rounding=ROUND_HALF_UP))
    unmatched_bank_volume = float(sum((abs(_to_dec(u["amount"])) for u in unmatched_bank_txns), Decimal("0.00")).quantize(_CENT, rounding=ROUND_HALF_UP))
    duplicate_volume = float(sum((abs(_to_dec(d["amount"])) for d in duplicate_charges), Decimal("0.00")).quantize(_CENT, rounding=ROUND_HALF_UP))

    balanced = (
        len(unmatched_invoices) == 0
        and len(unmatched_bank_txns) == 0
        and len(duplicate_charges) == 0
    )

    summary_metrics = {
        "matched_count": len(matched),
        "unmatched_invoice_count": len(unmatched_invoices),
        "unmatched_bank_txn_count": len(unmatched_bank_txns),
        "duplicate_count": len(duplicate_charges),
        "matched_volume": matched_volume,
        "unmatched_invoice_volume": unmatched_inv_volume,
        "unmatched_bank_volume": unmatched_bank_volume,
        "duplicate_exposure": duplicate_volume,
    }

    return ReconciliationReport(
        matched=matched,
        unmatched_invoices=unmatched_invoices,
        unmatched_bank_txns=unmatched_bank_txns,
        duplicate_charges=duplicate_charges,
        summary_metrics=summary_metrics,
        reconciliation_balanced=balanced,
    )
