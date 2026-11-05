"""
Privacy-safe real-time telemetry, analytics dashboard (`/analytics`, `/api/analytics`),
and ChatGPT Actions OpenAPI 3.1.0 specification (`/chatgpt-openapi.json`) for BillTally.

Zero customer financial data, bill text, or PII is ever stored: only aggregate counters
and anonymized event metadata (timestamp, platform, tool name, format/detail).
"""

from collections import deque
from datetime import datetime, timezone
import html
from typing import Any, Deque, Dict

from app.studio_pages import SHARED_PAGE_STYLE

_COUNTERS: Dict[str, int] = {
    "total_events": 0,
    "mcp_connections": 0,
    "tool_calls_total": 0,
    "spreadsheet_downloads": 0,
    "web_page_views": 0,
    "pro_unlocks": 0,
}

_BY_SOURCE: Dict[str, int] = {
    "Claude": 0,
    "ChatGPT": 0,
    "Web Desk": 0,
    "Other MCP Client": 0,
}

_BY_TOOL: Dict[str, int] = {
    "extract_financial_documents": 0,
    "reconcile_invoices_with_bank_ledger": 0,
    "export_ledger_bundle": 0,
}

_RECENT_EVENTS: Deque[Dict[str, str]] = deque(maxlen=50)


def detect_source(user_agent: str, path: str = "", client_name: str = "") -> str:
    """Classify the request caller as Claude, ChatGPT, Web Desk, or Other MCP Client."""
    ua = (user_agent or "").lower()
    cn = (client_name or "").lower()
    if "claude" in ua or "anthropic" in ua or "claude" in cn or "anthropic" in cn:
        return "Claude"
    if "chatgpt" in ua or "openai" in ua or "gpt" in cn or "/chatgpt" in path:
        return "ChatGPT"
    if path.startswith("/mcp"):
        return "Claude" if not ua or "python" not in ua else "Other MCP Client"
    return "Web Desk"


def record_event(
    *,
    event_type: str,
    source: str,
    tool_name: str = "-",
    detail: str = "",
) -> None:
    """Record a privacy-safe telemetry event in memory."""
    _COUNTERS["total_events"] += 1
    if source in _BY_SOURCE:
        _BY_SOURCE[source] += 1
    else:
        _BY_SOURCE["Other MCP Client"] += 1

    if event_type == "mcp_connect":
        _COUNTERS["mcp_connections"] += 1
    elif event_type == "tool_call":
        _COUNTERS["tool_calls_total"] += 1
        if tool_name in _BY_TOOL:
            _BY_TOOL[tool_name] += 1
    elif event_type == "spreadsheet_download":
        _COUNTERS["spreadsheet_downloads"] += 1
    elif event_type == "page_view":
        _COUNTERS["web_page_views"] += 1
    elif event_type == "pro_unlock":
        _COUNTERS["pro_unlocks"] += 1

    safe_tool = str(tool_name or "-")[:80]
    safe_detail = str(detail or "-")[:80]
    _RECENT_EVENTS.appendleft(
        {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "source": str(source or "Web Desk")[:40],
            "event": str(event_type or "-")[:40],
            "tool": safe_tool,
            "detail": safe_detail,
        }
    )


def get_analytics_snapshot() -> Dict[str, Any]:
    """Return current telemetry counters and recent anonymized events."""
    return {
        "service": "BillTally",
        "counters": dict(_COUNTERS),
        "by_source": dict(_BY_SOURCE),
        "by_tool": dict(_BY_TOOL),
        "recent_events": list(_RECENT_EVENTS),
    }


def render_analytics_html() -> str:
    """Render the live HTML Analytics Dashboard for BillTally across Claude, ChatGPT, and Web."""
    snap = get_analytics_snapshot()
    c = snap["counters"]
    src = snap["by_source"]
    tools = snap["by_tool"]
    rows = "".join(
        f"<tr><td>{html.escape(str(ev['timestamp']), quote=True)}</td>"
        f"<td><strong>{html.escape(str(ev['source']), quote=True)}</strong></td>"
        f"<td>{html.escape(str(ev['event']), quote=True)}</td>"
        f"<td><code>{html.escape(str(ev['tool']), quote=True)}</code></td>"
        f"<td>{html.escape(str(ev['detail']), quote=True)}</td></tr>"
        for ev in snap["recent_events"]
    ) or '<tr><td colspan="5" style="color:#6b6b6b;">No events recorded yet in this container session.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Live Analytics (Claude, ChatGPT &amp; Web) | BillTally</title>
  {SHARED_PAGE_STYLE}
  <style>
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(175px, 1fr)); gap: 12px; margin-top: 14px; }}
    .stat-card {{ background: var(--ground); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; }}
    .stat-val {{ font-size: 26px; font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; }}
    .stat-lbl {{ font-size: 12.5px; color: var(--muted); margin-top: 2px; }}
  </style>
</head>
<body>
  <main style="max-width:960px;">
    <nav class="top-nav" aria-label="Analytics navigation">
      <a href="/">← Return to BillTally Check Desk</a>
      <div class="links">
        <a href="/analytics">↻ Refresh Live Telemetry</a>
        <a href="/api/analytics">JSON Feed</a>
        <a href="/docs">Documentation</a>
        <a href="/about">About</a>
      </div>
    </nav>
    <h1>BillTally Live Analytics</h1>
    <p style="color:var(--muted); margin-top:4px;">Real-time, privacy-safe usage telemetry across <strong>Claude Connectors</strong>, <strong>ChatGPT</strong>, and the <strong>Web Check Desk</strong> (zero customer bill or statement text stored).</p>

    <div class="grid">
      <div class="stat-card"><div class="stat-val">{src.get('Claude', 0)}</div><div class="stat-lbl">Claude MCP Events</div></div>
      <div class="stat-card"><div class="stat-val">{src.get('ChatGPT', 0)}</div><div class="stat-lbl">ChatGPT Events</div></div>
      <div class="stat-card"><div class="stat-val">{src.get('Web Desk', 0)}</div><div class="stat-lbl">Web Desk Events</div></div>
      <div class="stat-card"><div class="stat-val">{c.get('tool_calls_total', 0)}</div><div class="stat-lbl">Total Tool Runs</div></div>
      <div class="stat-card"><div class="stat-val">{c.get('spreadsheet_downloads', 0)}</div><div class="stat-lbl">Excel / CSV Downloads</div></div>
      <div class="stat-card"><div class="stat-val">{c.get('pro_unlocks', 0)}</div><div class="stat-lbl">Pro Plan Activations</div></div>
    </div>

    <h2>Tool Breakdown</h2>
    <div class="grid">
      <div class="stat-card"><div class="stat-val">{tools.get('extract_financial_documents', 0)}</div><div class="stat-lbl">Check Supplier Bill Math</div></div>
      <div class="stat-card"><div class="stat-val">{tools.get('reconcile_invoices_with_bank_ledger', 0)}</div><div class="stat-lbl">Match Bank Statement</div></div>
      <div class="stat-card"><div class="stat-val">{tools.get('export_ledger_bundle', 0)}</div><div class="stat-lbl">Export Excel / CSV Bundle</div></div>
    </div>

    <h2>Recent Activity Feed (Last 50 Events)</h2>
    <table>
      <thead>
        <tr><th>Timestamp</th><th>Platform</th><th>Event</th><th>Tool</th><th>Detail</th></tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </main>
</body>
</html>"""


def build_chatgpt_openapi(base_url: str) -> Dict[str, Any]:
    """Return the OpenAPI 3.1.0 specification for ChatGPT custom plugin / GPT Actions."""
    ok_resp = {
        "200": {
            "description": "Successful plain-English bookkeeping verification response.",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "status": {"type": "string"},
                        },
                    }
                }
            },
        }
    }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "BillTally: Invoice & Receipt Extractor",
            "description": (
                "Check supplier bills and receipts to the penny using fixed-decimal arithmetic, "
                "match invoices against bank statement withdrawals to spot duplicate charges, "
                "and export 3-tab Microsoft Excel (.xlsx) workbooks with live =SUM() formulas or accounting CSVs."
            ),
            "version": "1.0.0",
        },
        "servers": [{"url": base_url}],
        "paths": {
            "/api/extract": {
                "post": {
                    "operationId": "extractFinancialDocuments",
                    "summary": "Check a supplier bill or receipt for line-item math errors, 1099-NEC flags, and overcharges.",
                    "x-openai-isConsequential": False,
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["raw_text"],
                                    "properties": {
                                        "raw_text": {
                                            "type": "string",
                                            "description": "Raw supplier bill, receipt, or statement text to verify.",
                                        },
                                        "document_type": {
                                            "type": "string",
                                            "enum": ["invoice", "bank_statement", "receipt", "contract", "auto"],
                                            "default": "auto",
                                            "description": "Type of financial document being checked.",
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "responses": ok_resp,
                }
            },
            "/api/reconcile": {
                "post": {
                    "operationId": "reconcileInvoicesWithBankLedger",
                    "summary": "Match supplier bills against bank statement withdrawals and catch duplicate charges.",
                    "x-openai-isConsequential": False,
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["invoices", "bank_transactions"],
                                    "properties": {
                                        "invoices": {
                                            "type": "array",
                                            "description": "List of bills with invoice_number, vendor, date, and total.",
                                            "items": {"type": "object"},
                                        },
                                        "bank_transactions": {
                                            "type": "array",
                                            "description": "List of bank withdrawals with txn_id, date, description, and amount.",
                                            "items": {"type": "object"},
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "responses": ok_resp,
                }
            },
            "/api/export": {
                "post": {
                    "operationId": "exportLedgerBundle",
                    "summary": "Export checked bills into a 3-tab Excel (.xlsx) workbook with live =SUM() formulas or accounting CSV.",
                    "x-openai-isConsequential": False,
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["documents"],
                                    "properties": {
                                        "documents": {
                                            "type": "array",
                                            "description": "Checked bill objects from extractFinancialDocuments.",
                                            "items": {"type": "object"},
                                        },
                                        "format": {
                                            "type": "string",
                                            "enum": ["xlsx", "csv", "quickbooks_csv"],
                                            "default": "xlsx",
                                            "description": "Spreadsheet output format (xlsx, csv, or quickbooks_csv).",
                                        },
                                        "use_corrected_amounts": {
                                            "type": "boolean",
                                            "default": False,
                                            "description": "Export verified true math totals instead of overcharged billed totals.",
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "responses": ok_resp,
                }
            },
        },
    }
