"""
Invoice-to-Bank-Ledger Reconciliation Engine (`reconcile_invoices_with_bank_ledger`).
Cross-matches extracted invoices/receipts against bank statement transactions using:
1) Exact / tolerance-bounded amount comparison
2) Settlement date tolerance window (`date_tolerance_days`)
3) Vendor token-overlap similarity
4) Duplicate charge detection (identical vendor + amount billed/debited multiple times)
"""

import re
from datetime import date, datetime
from typing import Any, Dict, List, Set, Tuple

from app.models import ReconcileLedgerRequest, ReconciliationReport

_STOP_WORDS = {"inc", "llc", "corp", "ltd", "ab", "co", "ach", "debit", "wire", "out", "card", "charge", "corp", "the"}


def _parse_iso_date(val: Any) -> date:
    text = str(val or "2026-10-01").strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return date(2026, 10, 1)


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
    matched_txn_ids: Set[str],
) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """Identify duplicate bank debits having the same normalized vendor token and amount within 5 days."""
    duplicates: List[Dict[str, Any]] = []
    duplicate_txn_ids: Set[str] = set()
    seen: List[Tuple[Set[str], float, date, Dict[str, Any]]] = []

    for idx, txn in enumerate(bank_transactions):
        txn_id = str(txn.get("txn_id", f"TXN-{idx+1}"))
        amt = round(float(txn.get("amount", 0.0)), 2)
        dt = _parse_iso_date(txn.get("date"))
        tokens = _vendor_tokens(str(txn.get("description", "")))

        is_dup_of = None
        for prev_tokens, prev_amt, prev_dt, prev_txn in seen:
            same_amt = abs(amt - prev_amt) <= 0.01
            close_date = abs((dt - prev_dt).days) <= 5
            shared_vendor = len(tokens & prev_tokens) >= 1
            if same_amt and close_date and shared_vendor:
                is_dup_of = prev_txn
                break

        if is_dup_of is not None:
            duplicate_txn_ids.add(txn_id)
            duplicates.append(
                {
                    "duplicate_txn_id": txn_id,
                    "original_txn_id": str(is_dup_of.get("txn_id", "UNKNOWN")),
                    "date": str(txn.get("date", "")),
                    "description": str(txn.get("description", "")),
                    "amount": amt,
                    "currency": str(txn.get("currency", "USD")),
                    "reason": (
                        f"Duplicate bank charge of {amt:.2f} within "
                        f"{abs((dt - _parse_iso_date(is_dup_of.get('date'))).days)} day(s) of {is_dup_of.get('txn_id')}."
                    ),
                }
            )
        else:
            seen.append((tokens, amt, dt, txn))

    return duplicates, duplicate_txn_ids


def reconcile_invoices_with_bank_ledger(req: ReconcileLedgerRequest) -> ReconciliationReport:
    """
    Cross-match extracted invoices against bank statement transactions.
    Pure function returning a new immutable `ReconciliationReport`.
    """
    matched: List[Dict[str, Any]] = []
    unmatched_invoices: List[Dict[str, Any]] = []
    used_bank_indices: Set[int] = set()

    for inv in req.invoices:
        inv_num = str(inv.get("invoice_number", "INV-UNKNOWN"))
        inv_vendor = str(inv.get("vendor", "Unknown Vendor"))
        inv_amt = round(float(inv.get("total", inv.get("amount", 0.0))), 2)
        inv_date = _parse_iso_date(inv.get("date", inv.get("issue_date", "2026-10-01")))
        inv_curr = str(inv.get("currency", "USD"))

        best_idx = None
        best_score = -1.0
        best_days = 999

        for b_idx, txn in enumerate(req.bank_transactions):
            if b_idx in used_bank_indices:
                continue
            txn_amt = round(float(txn.get("amount", 0.0)), 2)
            amt_diff = abs(inv_amt - txn_amt)
            if amt_diff > req.amount_tolerance:
                continue

            txn_date = _parse_iso_date(txn.get("date", "2026-10-01"))
            days_delta = abs((txn_date - inv_date).days)
            if days_delta > req.date_tolerance_days:
                continue

            sim = _vendor_similarity(inv_vendor, str(txn.get("description", "")))
            if sim <= 0.0:
                continue

            score = sim * 100.0 - days_delta - (amt_diff * 10.0)
            if score > best_score:
                best_score = score
                best_idx = b_idx
                best_days = days_delta

        if best_idx is not None:
            used_bank_indices.add(best_idx)
            matched_txn = req.bank_transactions[best_idx]
            matched.append(
                {
                    "invoice_number": inv_num,
                    "vendor": inv_vendor,
                    "invoice_date": str(inv_date),
                    "bank_txn_id": str(matched_txn.get("txn_id", f"TXN-{best_idx+1}")),
                    "bank_date": str(matched_txn.get("date", "")),
                    "bank_description": str(matched_txn.get("description", "")),
                    "invoice_amount": inv_amt,
                    "bank_amount": round(float(matched_txn.get("amount", 0.0)), 2),
                    "currency": inv_curr,
                    "settlement_lag_days": best_days,
                    "match_confidence": round(min(0.99, 0.85 + 0.14 * _vendor_similarity(inv_vendor, str(matched_txn.get("description", "")))), 2),
                }
            )
        else:
            unmatched_invoices.append(
                {
                    "invoice_number": inv_num,
                    "vendor": inv_vendor,
                    "date": str(inv_date),
                    "total": inv_amt,
                    "currency": inv_curr,
                    "status": "UNMATCHED_INVOICE_ACCRUAL_PENDING",
                }
            )

    matched_txn_ids = {m["bank_txn_id"] for m in matched}
    duplicate_charges, duplicate_txn_ids = _detect_duplicate_bank_charges(
        req.bank_transactions, matched_txn_ids
    )

    unmatched_bank_txns: List[Dict[str, Any]] = []
    for b_idx, txn in enumerate(req.bank_transactions):
        if b_idx in used_bank_indices:
            continue
        txn_id = str(txn.get("txn_id", f"TXN-{b_idx+1}"))
        status = (
            "DUPLICATE_DEBIT_ALERT"
            if txn_id in duplicate_txn_ids
            else "UNRECEIPTED_BANK_DEBIT"
        )
        unmatched_bank_txns.append(
            {
                "txn_id": txn_id,
                "date": str(txn.get("date", "")),
                "description": str(txn.get("description", "")),
                "amount": round(float(txn.get("amount", 0.0)), 2),
                "currency": str(txn.get("currency", "USD")),
                "status": status,
            }
        )

    matched_volume = round(sum(m["bank_amount"] for m in matched), 2)
    unmatched_inv_volume = round(sum(u["total"] for u in unmatched_invoices), 2)
    unmatched_bank_volume = round(sum(u["amount"] for u in unmatched_bank_txns), 2)
    duplicate_volume = round(sum(d["amount"] for d in duplicate_charges), 2)

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
