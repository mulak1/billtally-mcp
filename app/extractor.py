"""
Deterministic Financial Document Extractor & Mathematical Reconciliation Engine.
Uses Decimal arithmetic for zero floating-point drift when verifying:
1) line_item.quantity * line_item.unit_price == line_item.amount
2) sum(line_item.expected_amount) == subtotal
3) subtotal + tax == total  AND  sum(line_item.expected_amount) + tax == total
"""

import base64
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from app.models import (
    ExtractDocumentRequest,
    ExtractedDocumentResult,
    LineItem,
    MathDiscrepancy,
)

_CENT = Decimal("0.01")


def _to_dec(val: Any) -> Decimal:
    if isinstance(val, Decimal):
        return val.quantize(_CENT, rounding=ROUND_HALF_UP)
    if isinstance(val, (int, float)):
        return Decimal(str(val)).quantize(_CENT, rounding=ROUND_HALF_UP)
    cleaned = re.sub(r"[^0-9.\-]", "", str(val or "0"))
    if not cleaned or cleaned in ("-", ".", "-."):
        return Decimal("0.00")
    return Decimal(cleaned).quantize(_CENT, rounding=ROUND_HALF_UP)


def _decode_if_structured(raw_text: str) -> Optional[Dict[str, Any]]:
    """Decode base64: payloads or direct JSON payloads if provided."""
    text = raw_text.strip()
    if text.startswith("base64:"):
        b64_part = text[len("base64:") :].strip()
        decoded = base64.b64decode(b64_part).decode("utf-8")
        return json.loads(decoded)
    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _extract_header_field(text: str, patterns: List[str], default: str) -> str:
    for pat in patterns:
        match = re.search(pat, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            val = match.group(1).strip()
            if val:
                return val
    return default


def _infer_category(vendor: str, text: str) -> str:
    combined = f"{vendor} {text}".lower()
    if any(w in combined for w in ("flour", "pantry", "bakery", "butter", "food", "kitchen")):
        return "Cost of Goods Sold: Food & Pantry"
    if any(w in combined for w in ("plumbing", "heating", "repair", "pipe", "hvac", "maintenance")):
        return "Repairs & Building Maintenance"
    if any(w in combined for w in ("water", "power", "electric", "utility", "gas")):
        return "Utilities & Occupancy"
    if any(w in combined for w in ("linen", "laundry", "apron", "cleaning", "grounds", "snow")):
        return "Outside Services & Operations"
    return "General Operating Expense"


def _compute_payment_terms(issue_date: str, due_date: Optional[str]) -> str:
    if not due_date:
        return "Due on Receipt"
    try:
        d1 = datetime.strptime(issue_date[:10], "%Y-%m-%d").date()
        d2 = datetime.strptime(due_date[:10], "%Y-%m-%d").date()
        days = (d2 - d1).days
        if days > 0:
            return f"Net {days} (Due {due_date[:10]})"
    except ValueError:
        pass
    return f"Due {due_date[:10]}"


def _parse_line_items_from_text(text: str) -> List[Dict[str, Any]]:
    """Extract line items from pipe-delimited rows, markdown tables, tab/space columns, or natural lines."""
    items: List[Dict[str, Any]] = []
    explicit_pipe = re.compile(
        r"^(?:\d+[\.\)]\s*)?(?P<desc>[^|\n]+?)\s*\|\s*Qty:\s*(?P<qty>-?\d+(?:\.\d+)?)\s*\|\s*"
        r"Unit Price:\s*(?P<unit>-?\s*[$€£]?\s*-?[\d,]+(?:\.\d+)?)\s*\|\s*Amount:\s*(?P<amt>-?\s*[$€£]?\s*-?[\d,]+(?:\.\d+)?)",
        flags=re.IGNORECASE | re.MULTILINE,
    )
    for m in explicit_pipe.finditer(text):
        items.append(
            {
                "description": m.group("desc").strip(),
                "quantity": float(_to_dec(m.group("qty"))),
                "unit_price": float(_to_dec(m.group("unit"))),
                "amount": float(_to_dec(m.group("amt"))),
            }
        )
    if items:
        return items

    md_row = re.compile(
        r"^\s*\|\s*(?P<desc>[^|\n]+?)\s*\|\s*(?P<qty>-?\d+(?:\.\d+)?)\s*\|\s*"
        r"[$€£]?(?P<unit>-?[\d,]+(?:\.\d+)?)\s*\|\s*[$€£]?(?P<amt>-?[\d,]+(?:\.\d+)?)\s*\|\s*$",
        flags=re.MULTILINE,
    )
    for m in md_row.finditer(text):
        desc = m.group("desc").strip()
        if desc.lower() in ("description", "item", "---", ":---"):
            continue
        items.append(
            {
                "description": desc,
                "quantity": float(_to_dec(m.group("qty"))),
                "unit_price": float(_to_dec(m.group("unit"))),
                "amount": float(_to_dec(m.group("amt"))),
            }
        )
    if items:
        return items

    inline_pat = re.compile(
        r"^(?:\d+[\.\)]\s*)?(?P<desc>[A-Za-z0-9][^\n:]+?)\s+(?P<qty>\d+(?:\.\d+)?)\s*(?:[x×@]|\s{2,}|\t)\s*"
        r"[$€£]?(?P<unit>-?[\d,]+(?:\.\d+)?)\s*(?:=|\s{2,}|\t|\s+)\s*[$€£]?(?P<amt>-?[\d,]+(?:\.\d+)?)\s*$",
        flags=re.MULTILINE,
    )
    for m in inline_pat.finditer(text):
        items.append(
            {
                "description": m.group("desc").strip(),
                "quantity": float(_to_dec(m.group("qty"))),
                "unit_price": float(_to_dec(m.group("unit"))),
                "amount": float(_to_dec(m.group("amt"))),
            }
        )
    return items


def _extract_totals(text: str, raw_items: List[Dict[str, Any]]) -> Tuple[Decimal, Decimal, Decimal]:
    """Extract reported subtotal, tax, and total from text with sensible fallbacks."""
    sub_match = re.search(r"\bSubtotal\s*[:\-]?\s*(-?\s*[$€£]?\s*-?[\d,]+(?:\.\d+)?)", text, re.IGNORECASE)
    tax_match = re.search(r"\bTax(?:\s*\([^\)]+\))?\s*[:\-]?\s*(-?\s*[$€£]?\s*-?[\d,]+(?:\.\d+)?)", text, re.IGNORECASE)
    tot_match = re.search(r"\b(?:Grand\s+)?Total(?:\s+Due|\s+Amount)?\s*[:\-]?\s*(-?\s*[$€£]?\s*-?[\d,]+(?:\.\d+)?)", text, re.IGNORECASE)

    item_sum = sum((_to_dec(i["amount"]) for i in raw_items), Decimal("0.00"))
    subtotal = _to_dec(sub_match.group(1)) if sub_match else item_sum
    tax = _to_dec(tax_match.group(1)) if tax_match else Decimal("0.00")
    total = _to_dec(tot_match.group(1)) if tot_match else (subtotal + tax)
    return subtotal, tax, total


def extract_financial_document(
    req: ExtractDocumentRequest,
    quota_state: Optional[Dict[str, Any]] = None,
) -> ExtractedDocumentResult:
    """
    Parse a financial document and execute deterministic cent-level mathematical reconciliation.
    Returns a new immutable `ExtractedDocumentResult`.
    """
    structured = _decode_if_structured(req.raw_text)
    if structured is not None:
        vendor = str(structured.get("vendor", "Unknown Supplier"))
        invoice_number = str(structured.get("invoice_number", "INV-UNKNOWN"))
        issue_date = str(structured.get("issue_date", "2026-10-01"))
        due_date = structured.get("due_date")
        currency = str(req.currency_hint or structured.get("currency", "USD")).upper()
        raw_items = list(structured.get("line_items", []))
        subtotal = _to_dec(structured.get("subtotal", sum(_to_dec(i.get("amount", 0)) for i in raw_items)))
        tax = _to_dec(structured.get("tax", 0))
        total = _to_dec(structured.get("total", subtotal + tax))
    else:
        text = req.raw_text
        vendor = _extract_header_field(
            text,
            [r"Vendor\s*:\s*([^\n]+)", r"From\s*:\s*([^\n]+)", r"INVOICE STATEMENT\s*[:\-]\s*([^\n]+)"],
            "Unclassified Supplier",
        )
        invoice_number = _extract_header_field(
            text,
            [r"Invoice(?:\s+Number|\s*#)?\s*:\s*([A-Za-z0-9\-_]+)", r"Statement\s*#\s*:\s*([A-Za-z0-9\-_]+)"],
            "INV-UNNUMBERED",
        )
        issue_date = _extract_header_field(text, [r"(?:Issue\s+)?Date\s*:\s*(\d{4}-\d{2}-\d{2})"], "2026-10-01")
        due_raw = _extract_header_field(text, [r"Due\s+Date\s*:\s*(\d{4}-\d{2}-\d{2})"], "")
        due_date = due_raw if due_raw else None
        currency = (req.currency_hint or _extract_header_field(text, [r"Currency\s*:\s*([A-Z]{3})"], "USD")).upper()
        raw_items = _parse_line_items_from_text(text)
        subtotal, tax, total = _extract_totals(text, raw_items)

    normalized_items: List[LineItem] = []
    discrepancies: List[MathDiscrepancy] = []
    computed_subtotal = Decimal("0.00")

    for idx, item in enumerate(raw_items, start=1):
        qty = _to_dec(item.get("quantity", 1))
        unit = _to_dec(item.get("unit_price", 0))
        reported_amt = _to_dec(item.get("amount", 0))
        expected_amt = (qty * unit).quantize(_CENT, rounding=ROUND_HALF_UP)
        line_delta = (reported_amt - expected_amt).quantize(_CENT, rounding=ROUND_HALF_UP)
        line_valid = line_delta == Decimal("0.00")
        computed_subtotal = (computed_subtotal + expected_amt).quantize(_CENT, rounding=ROUND_HALF_UP)

        normalized_items.append(
            LineItem(
                line_number=idx,
                description=str(item.get("description", f"Line Item {idx}")),
                quantity=float(qty),
                unit_price=float(unit),
                amount=float(reported_amt),
                expected_amount=float(expected_amt),
                delta=float(line_delta),
                line_math_valid=line_valid,
            )
        )
        if not line_valid:
            discrepancies.append(
                MathDiscrepancy(
                    field=f"line_item_{idx}",
                    expected=float(expected_amt),
                    reported=float(reported_amt),
                    delta=float(line_delta),
                    severity="HIGH",
                    explanation=(
                        f"Line {idx} ({item.get('description')}): "
                        f"{qty} × ${unit:,.2f} should be ${expected_amt:,.2f}, "
                        f"but the bill lists ${reported_amt:,.2f} (a ${line_delta:+,.2f} difference)."
                    ),
                )
            )

    if not normalized_items and subtotal > Decimal("0.00"):
        computed_subtotal = subtotal

    subtotal_delta = (subtotal - computed_subtotal).quantize(_CENT, rounding=ROUND_HALF_UP)
    if subtotal_delta != Decimal("0.00"):
        discrepancies.append(
            MathDiscrepancy(
                field="subtotal",
                expected=float(computed_subtotal),
                reported=float(subtotal),
                delta=float(subtotal_delta),
                severity="HIGH",
                explanation=(
                    f"Subtotal difference: the line items add up to ${computed_subtotal:,.2f}, "
                    f"but the bill shows a subtotal of ${subtotal:,.2f} (${subtotal_delta:+,.2f})."
                ),
            )
        )

    computed_total = (computed_subtotal + tax).quantize(_CENT, rounding=ROUND_HALF_UP)
    total_delta = (total - computed_total).quantize(_CENT, rounding=ROUND_HALF_UP)
    if total_delta != Decimal("0.00"):
        discrepancies.append(
            MathDiscrepancy(
                field="total",
                expected=float(computed_total),
                reported=float(total),
                delta=float(total_delta),
                severity="HIGH",
                explanation=(
                    f"Total difference: true subtotal (${computed_subtotal:,.2f}) + tax (${tax:,.2f}) "
                    f"= ${computed_total:,.2f}, but the bill asks for ${total:,.2f} (${total_delta:+,.2f})."
                ),
            )
        )

    math_verified = len(discrepancies) == 0
    doc_hash = hashlib.sha256(f"{vendor}:{invoice_number}:{total}".encode("utf-8")).hexdigest()[:12]
    doc_type = req.document_type if req.document_type != "auto" else "invoice"
    confidence = 0.98 if (math_verified and len(normalized_items) > 0) else (0.82 if normalized_items else 0.55)
    category = _infer_category(vendor, req.raw_text)
    terms = _compute_payment_terms(issue_date, due_date)
    eff_tax = float(round((tax / computed_subtotal) * Decimal("100"), 2)) if computed_subtotal > 0 else 0.0
    needs_1099 = ("Repairs" in category or "Services" in category) and float(computed_total) >= 600.0

    seen_lines: Dict[Tuple[str, float], int] = {}
    dup_labels: List[str] = []
    for li in normalized_items:
        sig = (li.description.strip().lower(), round(li.amount, 2))
        seen_lines[sig] = seen_lines.get(sig, 0) + 1
        if seen_lines[sig] == 2:
            dup_labels.append(f"{li.description} (${li.amount:,.2f})")
    dup_count = sum(c - 1 for c in seen_lines.values() if c > 1)
    dup_warning = (
        f"Potential duplicate line item: {', '.join(dup_labels)} appears more than once on this bill."
        if dup_count > 0
        else None
    )
    high_tax_warning = (
        f"High effective tax rate ({eff_tax:.2f}% > 12%): verify local tax rate or non-taxable fees."
        if eff_tax > 12.0
        else None
    )

    if math_verified:
        plain_summary = (
            f"All {len(normalized_items)} line items and tax add up to the penny "
            f"({currency} ${total:,.2f}). Ready to approve and export."
        )
        dispute_note = None
    else:
        direction = "overcharged" if total_delta > 0 else "under-billed"
        plain_summary = (
            f"Hold payment: This bill from {vendor} is {direction} by ${abs(total_delta):,.2f}. "
            f"The true total is ${computed_total:,.2f}, not ${total:,.2f}."
        )
        bullet_lines = "\n".join(f"- {d.explanation}" for d in discrepancies)
        dispute_note = (
            f"Hi {vendor} Billing Team,\n\n"
            f"We reviewed Invoice #{invoice_number} (dated {issue_date}) and noticed a math difference:\n"
            f"{bullet_lines}\n\n"
            f"Could you please send an updated bill for the corrected total of {currency} ${computed_total:,.2f} "
            f"(instead of ${total:,.2f}) so we can process payment right away?\n\nThank you!"
        )

    normalized_rows = [
        {
            "document_id": f"doc_{doc_hash}",
            "vendor": vendor,
            "invoice_number": invoice_number,
            "issue_date": issue_date,
            "due_date": due_date,
            "currency": currency,
            "category": category,
            "line_number": li.line_number,
            "description": li.description,
            "quantity": li.quantity,
            "unit_price": li.unit_price,
            "reported_amount": li.amount,
            "verified_amount": li.expected_amount,
            "line_math_valid": li.line_math_valid,
            "doc_math_verified": math_verified,
        }
        for li in normalized_items
    ]

    equation = (
        f"Items (${computed_subtotal:,.2f}) + Tax (${tax:,.2f}) = "
        f"${computed_total:,.2f} true total vs. ${total:,.2f} billed ({total_delta:+.2f})"
    )

    return ExtractedDocumentResult(
        document_id=f"doc_{doc_hash}",
        document_type=doc_type,
        vendor=vendor,
        invoice_number=invoice_number,
        issue_date=issue_date,
        due_date=due_date,
        payment_terms=terms,
        currency=currency,
        line_items=normalized_items,
        subtotal=float(subtotal),
        tax=float(tax),
        total=float(total),
        computed_subtotal=float(computed_subtotal),
        computed_total=float(computed_total),
        effective_tax_rate_pct=eff_tax,
        math_verified=math_verified,
        discrepancy_delta=float(total_delta),
        discrepancies=discrepancies,
        confidence_score=confidence,
        normalized_rows=normalized_rows,
        reconciliation_equation=equation,
        plain_english_summary=plain_summary,
        suggested_category=category,
        requires_1099_review=needs_1099,
        duplicate_line_items_count=dup_count,
        duplicate_line_items_warning=dup_warning,
        high_tax_rate_warning=high_tax_warning,
        vendor_dispute_note=dispute_note,
        quota_state=quota_state,
    )
