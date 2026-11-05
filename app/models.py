"""
Strict Pydantic v2 schemas and immutable boundary models for SchemaExtract MCP.
Enforces input boundary validation, immutability, and explicit typing.
"""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class LineItem(BaseModel):
    """Normalized line item with deterministic math check."""

    model_config = ConfigDict(frozen=True)

    line_number: int = Field(..., ge=1)
    description: str = Field(..., min_length=1, max_length=500)
    quantity: float = Field(...)
    unit_price: float = Field(...)
    amount: float = Field(...)
    expected_amount: float = Field(...)
    delta: float = Field(...)
    line_math_valid: bool = Field(...)


class MathDiscrepancy(BaseModel):
    """Detailed explanation of a line-item or subtotal/total math discrepancy."""

    model_config = ConfigDict(frozen=True)

    field: str
    expected: float
    reported: float
    delta: float
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    explanation: str


class ExtractDocumentRequest(BaseModel):
    """Input boundary schema for `extract_financial_documents`."""

    model_config = ConfigDict(frozen=True)

    raw_text: str = Field(
        ...,
        description="Raw text, table, or structured document content of a supplier bill, bank statement, receipt, or agreement.",
    )
    document_type: Literal["invoice", "bank_statement", "receipt", "contract", "auto"] = Field(
        default="auto",
        description="Document classification hint.",
    )
    currency_hint: Optional[str] = Field(
        default=None,
        max_length=10,
        description="Optional 3-letter currency code hint (e.g., USD, EUR, GBP).",
    )
    strict_reconciliation: bool = Field(
        default=True,
        description="Whether to enforce cent-level mathematical checking.",
    )
    workspace_id: str = Field(default="default-workspace", max_length=120)
    api_key: Optional[str] = Field(default=None, max_length=160)

    @field_validator("raw_text")
    @classmethod
    def validate_raw_text_bounds(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("raw_text cannot be empty or whitespace only.")
        if len(cleaned) > 250_000:
            raise ValueError("raw_text exceeds maximum boundary limit of 250,000 characters.")
        return cleaned


class ExtractedDocumentResult(BaseModel):
    """Output schema for `extract_financial_documents` with deterministic math audit."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    document_type: str
    vendor: str
    invoice_number: str
    issue_date: str
    due_date: Optional[str] = None
    payment_terms: str = "Due on Receipt"
    currency: str
    line_items: List[LineItem]
    subtotal: float
    tax: float
    total: float
    computed_subtotal: float
    computed_total: float
    effective_tax_rate_pct: float = 0.0
    math_verified: bool
    discrepancy_delta: float
    discrepancies: List[MathDiscrepancy]
    confidence_score: float
    normalized_rows: List[Dict[str, Any]]
    reconciliation_equation: str
    plain_english_summary: str = ""
    suggested_category: str = "General Operating Expense"
    requires_1099_review: bool = False
    duplicate_line_items_count: int = 0
    duplicate_line_items_warning: Optional[str] = None
    high_tax_rate_warning: Optional[str] = None
    vendor_dispute_note: Optional[str] = None
    quota_state: Optional[Dict[str, Any]] = None


class ReconcileLedgerRequest(BaseModel):
    """Input boundary schema for `reconcile_invoices_with_bank_ledger`."""

    model_config = ConfigDict(frozen=True)

    invoices: List[Dict[str, Any]] = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Extracted bills or receipts to match against bank statement rows.",
    )
    bank_transactions: List[Dict[str, Any]] = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Bank statement rows with date, description, and amount.",
    )
    date_tolerance_days: int = Field(
        default=7,
        ge=0,
        le=90,
        description="Maximum allowed calendar days between bill date and bank payment date.",
    )
    amount_tolerance: float = Field(
        default=0.05,
        ge=0.0,
        le=100.0,
        description="Allowed monetary tolerance for minor rounding differences.",
    )


class ReconciliationReport(BaseModel):
    """Output schema for `reconcile_invoices_with_bank_ledger`."""

    model_config = ConfigDict(frozen=True)

    matched: List[Dict[str, Any]]
    unmatched_invoices: List[Dict[str, Any]]
    unmatched_bank_txns: List[Dict[str, Any]]
    duplicate_charges: List[Dict[str, Any]]
    summary_metrics: Dict[str, Any]
    reconciliation_balanced: bool


class ExportBundleRequest(BaseModel):
    """Input boundary schema for `export_ledger_bundle`."""

    model_config = ConfigDict(frozen=True)

    documents: List[Dict[str, Any]] = Field(
        default_factory=list,
        max_length=500,
        description="List of checked bills or statements to include in the spreadsheet.",
    )
    reconciliation: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional bank matching summary to include as a separate worksheet tab.",
    )
    format: Literal["xlsx", "csv", "quickbooks_csv"] = Field(
        default="xlsx",
        description="Output format: multi-tab Excel workbook (`xlsx`), standard `csv`, or accounting-import `quickbooks_csv`.",
    )
    bundle_name: str = Field(
        default="schemaextract_ledger",
        min_length=1,
        max_length=120,
        description="Base filename for the generated spreadsheet.",
    )
    use_corrected_amounts: bool = Field(
        default=False,
        description="When True, exports verified math totals instead of overcharged billed figures.",
    )


class ExportBundleResult(BaseModel):
    """Output schema for `export_ledger_bundle`."""

    model_config = ConfigDict(frozen=True)

    filename: str
    format: str
    download_url: str
    size_bytes: int
    sha256_checksum: str
    base64_content: str
    sheets_included: List[str]
    row_count: int
    formulas_embedded: bool
