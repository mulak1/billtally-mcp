"""
Multimodal Invoice & Statement File Helper for BillTally (`POST /api/extract-file`).
Extracts clean structured invoice lines locally from digital `.pdf`, `.xlsx`, `.csv`, and `.txt`,
or falls back to Gemini 3.5 Flash-Lite Vision when `GEMINI_API_KEY` is set.
"""

from __future__ import annotations

import base64
import csv
from email.parser import BytesParser
from email.policy import default as email_default_policy
import io
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
import zipfile
import zlib

import httpx
import openpyxl

MAX_UPLOAD_BYTES = 5_000_000
MAX_STREAM_DECOMPRESS_BYTES = 8_000_000
MAX_XLSX_ENTRIES = 64
MAX_XLSX_UNCOMPRESSED_BYTES = 16_000_000
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".xlsx", ".csv", ".txt"}
IMAGE_MIME_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
_PDF_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "(": "(", ")": ")", "\\": "\\"}


def parse_upload_from_request(raw_body: bytes, content_type: str, query_params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Parse `multipart/form-data` or `application/json` upload payloads using Python stdlib."""
    if len(raw_body) > MAX_UPLOAD_BYTES:
        raise ValueError("Uploaded file exceeds the 5 MB limit.")
    qp = query_params or {}
    ctype = (content_type or "").strip()
    if "multipart/form-data" in ctype.lower():
        mime_blob = b"Content-Type: " + ctype.encode("latin-1", errors="ignore") + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw_body
        msg = BytesParser(policy=email_default_policy).parsebytes(mime_blob)
        fields, file_bytes, filename = {}, None, ""
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition") or ""
            fname = part.get_filename()
            payload = part.get_payload(decode=True) or b""
            if fname is not None or name in ("file", "bill_file"):
                file_bytes, filename = payload, (fname or "uploaded_bill.txt")
            elif name:
                fields[name] = payload.decode("utf-8", errors="ignore").strip()
        if file_bytes is None:
            raise ValueError("Missing file field in multipart upload.")
        src = {**qp, **fields}
        return {"filename": filename, "file_bytes": file_bytes, "document_type": src.get("document_type", "invoice"), "workspace_id": src.get("workspace_id", "default-workspace"), "api_key": src.get("api_key") or None, "currency_hint": src.get("currency_hint") or None, "strict_reconciliation": str(src.get("strict_reconciliation", "")).lower() in ("1", "true", "yes")}
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise ValueError("Expected multipart/form-data file upload or JSON {filename, content_base64}.") from exc
    if not isinstance(body, dict):
        raise ValueError("JSON upload payload must be an object.")
    b64_str = str(body.get("content_base64") or body.get("file_base64") or "").strip()
    if "," in b64_str and b64_str.lower().startswith("data:"):
        b64_str = b64_str.split(",", 1)[1].strip()
    if not b64_str:
        raise ValueError("Missing content_base64 in JSON upload request.")
    try:
        decoded = base64.b64decode(b64_str, validate=False)
    except Exception as exc:
        raise ValueError("Invalid base64 file content.") from exc
    if len(decoded) > MAX_UPLOAD_BYTES:
        raise ValueError("Decoded file exceeds the 5 MB limit.")
    return {"filename": str(body.get("filename") or "uploaded_bill.pdf"), "file_bytes": decoded, "document_type": str(body.get("document_type") or qp.get("document_type", "invoice")), "workspace_id": str(body.get("workspace_id") or qp.get("workspace_id", "default-workspace")), "api_key": body.get("api_key") or qp.get("api_key") or None, "currency_hint": body.get("currency_hint") or qp.get("currency_hint") or None, "strict_reconciliation": bool(body.get("strict_reconciliation", False))}


def _unescape_pdf_literal(raw: str) -> str:
    return re.sub(r"\\([0-7]{1,3}|.)", lambda m: _PDF_ESCAPES[m.group(1)] if m.group(1) in _PDF_ESCAPES else (chr(int(m.group(1), 8)) if m.group(1)[0].isdigit() else ("" if m.group(1) in ("\r", "\n") else m.group(1))), raw, flags=re.DOTALL)


def _decode_pdf_hex_string(hex_str: str) -> str:
    cleaned = re.sub(r"\s+", "", hex_str)
    try:
        raw = bytes.fromhex(cleaned + ("0" if len(cleaned) % 2 else ""))
    except ValueError:
        return ""
    return raw[2:].decode("utf-16-be", errors="ignore") if raw.startswith(b"\xfe\xff") else raw.decode("latin-1", errors="ignore")


def extract_pdf_text_local(raw_bytes: bytes) -> str:
    """Extract selectable text from digital PDF streams (uncompressed & FlateDecode) without external deps."""
    if not raw_bytes.lstrip().startswith(b"%PDF-"):
        raise ValueError("Invalid PDF file: missing %PDF- header.")
    lines: List[str] = []
    total_decompressed = 0
    token_re = re.compile(
        r"\((?:\\.|[^\\()])*\)\s*(?:Tj|')|\[((?:\((?:\\.|[^\\()])*\)|[^\[\]()]){0,16384})\]\s*TJ"
        r"|<([0-9A-Fa-f\s]+)>\s*Tj|(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+T[dD]|\b(?:T\*|ET)\b"
    )
    lit_or_kern_re = re.compile(r"\(((?:\\.|[^\\()])*)\)|<([0-9A-Fa-f\s]+)>|(-?\d+(?:\.\d+)?)")
    pos = 0
    stream_count = 0
    while stream_count < 512:
        s_idx = raw_bytes.find(b"stream", pos)
        if s_idx == -1:
            break
        body_start = s_idx + 6
        if raw_bytes[body_start : body_start + 2] == b"\r\n":
            body_start += 2
        elif raw_bytes[body_start : body_start + 1] == b"\n":
            body_start += 1
        else:
            pos = body_start
            continue
        e_idx = raw_bytes.find(b"endstream", body_start)
        if e_idx == -1:
            break
        pos = e_idx + 9
        stream_count += 1
        chunk = raw_bytes[body_start:e_idx].rstrip(b"\r\n")
        candidates = [chunk]
        for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
            try:
                budget_plus_one = (MAX_STREAM_DECOMPRESS_BYTES - total_decompressed) + 1
                dobj = zlib.decompressobj(wbits)
                dec = dobj.decompress(chunk, budget_plus_one)
                if dec:
                    if total_decompressed + len(dec) > MAX_STREAM_DECOMPRESS_BYTES or dobj.unconsumed_tail:
                        raise ValueError("PDF stream decompression limit exceeded (potential zip-bomb).")
                    total_decompressed += len(dec)
                    candidates.insert(0, dec)
                    break
            except zlib.error:
                continue
        for data in candidates:
            if b"Tj" not in data and b"TJ" not in data and b"'" not in data:
                continue
            cur_line: List[str] = []
            for tm in token_re.finditer(data.decode("latin-1", errors="ignore")):
                tok = tm.group(0)
                if tok in ("T*", "ET"):
                    if cur_line:
                        lines.append("".join(cur_line).strip())
                        cur_line = []
                elif tm.group(3) is not None and tm.group(4) is not None:
                    if abs(float(tm.group(4))) > 1.5 and cur_line:
                        lines.append("".join(cur_line).strip())
                        cur_line = []
                    elif float(tm.group(3)) > 8 and cur_line and not cur_line[-1].endswith(" "):
                        cur_line.append(" ")
                elif tm.group(1) is not None:
                    for pm in lit_or_kern_re.finditer(tm.group(1)):
                        if pm.group(1) is not None:
                            cur_line.append(_unescape_pdf_literal(pm.group(1)))
                        elif pm.group(2) is not None:
                            cur_line.append(_decode_pdf_hex_string(pm.group(2)))
                        elif pm.group(3) is not None and float(pm.group(3)) < -120 and cur_line and not cur_line[-1].endswith(" "):
                            cur_line.append(" ")
                elif tm.group(2) is not None:
                    cur_line.append(_decode_pdf_hex_string(tm.group(2)))
                else:
                    inner = re.match(r"\(((?:\\.|[^\\()])*)\)", tok)
                    if inner:
                        cur_line.append(_unescape_pdf_literal(inner.group(1)))
            if cur_line:
                lines.append("".join(cur_line).strip())
            break
    return "\n".join(ln for ln in lines if ln)


def _rows_to_invoice_text(rows: List[List[str]]) -> str:
    clean_rows = [[c.strip() for c in r] for r in rows if any(c.strip() for c in r)]
    if not clean_rows:
        raise ValueError("Uploaded spreadsheet/CSV contains no readable rows.")
    if all(len(r) == 1 for r in clean_rows):
        return "\n".join(r[0] for r in clean_rows)
    out_headers, out_items, out_totals, col_map = [], [], [], {}
    for r in clean_rows[:500]:
        non_empty = [c for c in r if c]
        low0 = r[0].lower().rstrip(":") if r else ""
        if not col_map and len(r) >= 3:
            lows = [c.lower().strip() for c in r]
            if any(k in h for h in lows for k in ("desc", "item", "service", "product")) and any(k in h for h in lows for k in ("amount", "total", "price", "rate", "cost")):
                for idx, h in enumerate(lows):
                    for tag, keys in (("desc", ("desc", "item", "service", "product")), ("qty", ("qty", "quant", "hours")), ("unit", ("unit", "price", "rate", "cost")), ("amt", ("amount", "total", "ext"))):
                        if any(k in h for k in keys):
                            col_map.setdefault(tag, idx)
                            break
                continue
        if low0 in ("vendor", "supplier", "from") and len(non_empty) >= 2:
            out_headers.append(f"Vendor: {non_empty[1]}")
        elif low0 in ("invoice", "invoice #", "invoice number", "bill #") and len(non_empty) >= 2:
            out_headers.append(f"Invoice #: {non_empty[1]}")
        elif low0 in ("date", "issue date", "due date", "currency") and len(non_empty) >= 2:
            out_headers.append(f"{r[0].strip().rstrip(':')}: {non_empty[1]}")
        elif any(low0.startswith(k) for k in ("subtotal", "tax", "sales tax", "total", "grand total")) and len(non_empty) >= 2:
            out_totals.append(f"{'Tax' if 'tax' in low0 else ('Subtotal' if 'sub' in low0 else 'Total')}: {non_empty[-1]}")
        elif col_map and "desc" in col_map:
            desc = r[col_map["desc"]] if col_map["desc"] < len(r) else ""
            if desc:
                qty = r[col_map["qty"]] if "qty" in col_map and col_map["qty"] < len(r) and r[col_map["qty"]] else "1"
                amt = r[col_map["amt"]] if "amt" in col_map and col_map["amt"] < len(r) else non_empty[-1]
                unit = r[col_map["unit"]] if "unit" in col_map and col_map["unit"] < len(r) and r[col_map["unit"]] else amt
                out_items.append(f"{len(out_items) + 1}. {desc} | Qty: {qty} | Unit Price: {unit} | Amount: {amt}")
        elif len(non_empty) >= 4:
            out_items.append(f"{len(out_items) + 1}. {non_empty[0]} | Qty: {non_empty[1]} | Unit Price: {non_empty[2]} | Amount: {non_empty[3]}")
        else:
            out_headers.append(" ".join(non_empty))
    return "\n".join([*out_headers, *out_items, *out_totals]).strip()


def call_gemini_vision_invoice(raw_bytes: bytes, mime_type: str, api_key: str) -> str:
    """Call Gemini 3.5 Flash-Lite multimodal vision via `x-goog-api-key` header and format invoice lines."""
    prompt = "Extract this financial bill/invoice into strict JSON: {vendor, invoice_number, issue_date, currency, line_items:[{description,quantity,unit_price,amount}], subtotal, tax, total}. Transcribe exact printed figures without altering vendor math."
    primary = os.environ.get("GEMINI_VISION_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite"
    payload = {
        "contents": [{"parts": [{"text": prompt}, {"inlineData": {"mimeType": mime_type, "data": base64.b64encode(raw_bytes).decode("ascii")}}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    last_err = "Vision OCR unavailable."
    for model in (primary, "gemini-2.5-flash"):
        try:
            resp = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", headers={"x-goog-api-key": api_key, "Content-Type": "application/json"}, json=payload, timeout=20.0)
            if resp.status_code == 404 and model != "gemini-2.5-flash":
                continue
            if resp.status_code >= 400:
                last_err = f"Gemini Vision HTTP {resp.status_code}"
                break
            body_json = resp.json()
            cands = body_json.get("candidates") if isinstance(body_json, dict) else None
            first_cand = cands[0] if isinstance(cands, list) and cands and isinstance(cands[0], dict) else {}
            content_obj = first_cand.get("content") if isinstance(first_cand.get("content"), dict) else {}
            parts = content_obj.get("parts") if isinstance(content_obj.get("parts"), list) else []
            raw_text = next((p.get("text") for p in parts if isinstance(p, dict) and not p.get("thought") and isinstance(p.get("text"), str)), "{}")
            parsed = json.loads(raw_text.strip() or "{}")
            if isinstance(parsed, list) and parsed:
                parsed = parsed[0]
            if not isinstance(parsed, dict):
                raise ValueError("Gemini Vision returned a non-object JSON payload.")
        except (httpx.HTTPError, json.JSONDecodeError, TypeError, KeyError, IndexError, ValueError) as exc:
            last_err = str(exc) if isinstance(exc, ValueError) else f"Vision OCR error: {type(exc).__name__}"
            break
        if not parsed.get("line_items") and parsed.get("total") is None and parsed.get("subtotal") is None and not parsed.get("vendor"):
            raise ValueError("No financial invoice or receipt figures detected in uploaded document.")
        issue_date = str(parsed.get("issue_date") or "").strip()
        lines = [f"Vendor: {parsed.get('vendor') or 'Unknown Supplier'}", f"Invoice #: {parsed.get('invoice_number') or 'INV-OCR'}"]
        if issue_date:
            lines.append(f"Date: {issue_date}")
        lines.append(f"Currency: {parsed.get('currency') or 'USD'}")
        for idx, it in enumerate((x for x in (parsed.get("line_items") or []) if isinstance(x, dict)), start=1):
            lines.append(f"{idx}. {it.get('description') or f'Item {idx}'} | Qty: {it.get('quantity', 1)} | Unit Price: ${it.get('unit_price', 0)} | Amount: ${it.get('amount', 0)}")
        lines.extend(f"{lbl}: ${parsed[k]}" for k, lbl in (("subtotal", "Subtotal"), ("tax", "Tax"), ("total", "Total")) if parsed.get(k) is not None)
        return "\n".join(lines)
    raise ValueError(f"Unable to extract scanned document via Vision OCR ({last_err}).")


def extract_invoice_text_from_upload(
    filename: str,
    raw_bytes: bytes,
    gemini_api_key: Optional[str] = None,
    before_vision_ocr: Optional[Callable[[], None]] = None,
) -> Tuple[str, str]:
    """Extract clean structured invoice text from `.pdf`, `.xlsx`, `.csv`, `.txt`, or image files."""
    if not raw_bytes or len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError("Uploaded file is empty." if not raw_bytes else "Uploaded file exceeds the 5 MB limit.")
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type '{ext or 'unknown'}'. Upload .pdf, .png, .jpg, .webp, .xlsx, .csv, or .txt.")
    key = (gemini_api_key if gemini_api_key is not None else os.environ.get("GEMINI_API_KEY", "")).strip()
    if ext == ".pdf":
        local_text = extract_pdf_text_local(raw_bytes)
        if len(re.sub(r"[^A-Za-z0-9]", "", local_text)) >= 20:
            return local_text, "pdf_text"
        if key:
            if before_vision_ocr:
                before_vision_ocr()
            return call_gemini_vision_invoice(raw_bytes, "application/pdf", key), "gemini_vision"
        raise ValueError("Scanned image PDF detected without selectable text; configure GEMINI_API_KEY for Vision OCR or upload a digital PDF/XLSX/CSV.")
    if ext in IMAGE_MIME_BY_EXT:
        if not (raw_bytes.startswith(b"\x89PNG") or raw_bytes.startswith(b"\xff\xd8\xff") or (raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP")):
            raise ValueError("Invalid image file header for receipt/invoice upload.")
        if not key:
            raise ValueError("Receipt/invoice photo OCR requires GEMINI_API_KEY on the server, or upload a digital PDF, Excel (.xlsx), or CSV.")
        if before_vision_ocr:
            before_vision_ocr()
        return call_gemini_vision_invoice(raw_bytes, IMAGE_MIME_BY_EXT[ext], key), "gemini_vision"
    if ext == ".xlsx":
        try:
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                infos = zf.infolist()
                if len(infos) > MAX_XLSX_ENTRIES:
                    raise ValueError("Excel (.xlsx) archive exceeds safe entry or uncompressed size limits.")
                real_total = 0
                for info in infos:
                    member_total = 0
                    with zf.open(info, "r") as zmember:
                        while True:
                            chunk = zmember.read(65536)
                            if not chunk:
                                break
                            real_total += len(chunk)
                            member_total += len(chunk)
                            if real_total > MAX_XLSX_UNCOMPRESSED_BYTES:
                                raise ValueError("Excel (.xlsx) archive exceeds safe entry or uncompressed size limits.")
                            if info.filename.lower().endswith("sharedstrings.xml") and member_total > 2_000_000:
                                raise ValueError("Excel (.xlsx) archive exceeds safe sharedStrings size limit.")
        except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, zlib.error, EOFError, NotImplementedError) as exc:
            raise ValueError("Invalid or corrupt Excel (.xlsx) workbook.") from exc
        try:
            wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), read_only=True, data_only=True)
            try:
                rows = [["" if v is None else str(v) for v in row] for ws in wb.worksheets[:3] for row in ws.iter_rows(max_row=500, max_col=50, values_only=True)]
            finally:
                wb.close()
        except Exception as exc:
            raise ValueError("Invalid or corrupt Excel (.xlsx) workbook.") from exc
        return _rows_to_invoice_text(rows), "xlsx_openpyxl"
    if raw_bytes.lstrip().startswith(b"%PDF-") or raw_bytes.startswith(b"PK\x03\x04") or b"\x00" in raw_bytes[:512]:
        raise ValueError("Binary file content detected in text/CSV upload; rename with .pdf or .xlsx extension.")
    decoded = raw_bytes.decode("utf-8-sig", errors="replace").strip()
    if not decoded:
        raise ValueError("Uploaded text/CSV file is empty.")
    return (_rows_to_invoice_text(list(csv.reader(io.StringIO(decoded)))), "csv_table") if ext == ".csv" else (decoded, "plain_text")
