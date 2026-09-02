"""Request/response schemas for the import API."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ImportStatus


class ReconciliationResult(BaseModel):
    """Outcome of checking our totals against Square's own Items Summary."""

    model_config = ConfigDict(frozen=True)

    performed: bool = Field(
        description="False when no Items Summary was supplied."
    )
    matches: bool
    net_sales_pence_ours: int = 0
    net_sales_pence_theirs: int = 0
    line_totals_pence_ours: int = 0
    line_totals_pence_theirs: int = 0
    units_ours: int = 0
    units_theirs: int = 0


class ImportSummary(BaseModel):
    """Result of one logical Square import."""

    model_config = ConfigDict(frozen=True)

    batch_id: int
    status: ImportStatus
    label: str | None = None

    period_start: date | None = Field(
        default=None,
        description=(
            "Inclusive first calendar day covered, in the business's own "
            "timezone. Derived from the file contents — client filenames are "
            "never trusted for coverage dates."
        ),
    )
    period_end: date | None = Field(
        default=None, description="Inclusive last calendar day covered."
    )

    orders_imported: int
    order_items_imported: int
    products_created: int
    products_reused: int

    rows_skipped: int
    issue_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Row-level outcomes keyed by code, e.g. "
        '{"zero_value_transaction": 57}.',
    )

    net_sales_pence: int = Field(
        description="Integer minor units (pence). Never a float."
    )
    reconciliation: ReconciliationResult


class ValidationIssue(BaseModel):
    """One request-validation problem, e.g. a missing or malformed parameter."""

    model_config = ConfigDict(frozen=True)

    location: str = Field(description='Where it occurred, e.g. "query.start_date".')
    message: str
    type: str


class ErrorResponse(BaseModel):
    """A safe, client-facing error, used by every endpoint.

    Carries no stack trace, no SQL and no source-row content.
    """

    model_config = ConfigDict(frozen=True)

    detail: str = Field(description="Human-readable explanation.")
    code: str = Field(description='Stable machine-readable code, e.g. "duplicate_file".')
    errors: list[ValidationIssue] | None = Field(
        default=None,
        description="Present only for request-validation failures (422).",
    )
