"""Source adapter interface and shared result types.

ARCHITECTURE.md §2: each data source gets a thin adapter whose only job is
mapping that source's shape into our canonical model. Nothing downstream of an
adapter knows what Square's columns are called.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from app.models.enums import ImportFileRole


class SourceError(Exception):
    """Base class for every adapter failure."""


class SourceFormatError(SourceError):
    """The file is not in the encoding/delimiter the adapter expects."""


class SourceSchemaError(SourceError):
    """The file parsed, but does not carry the columns the adapter requires."""


class IssueCode(str, Enum):
    """Why a row could not be normalised, or was normalised with a caveat.

    These are *explicit outcomes*, not silent guesses. A row the adapter cannot
    confidently interpret is reported, never assumed.
    """

    UNRESOLVED_CHANNEL = "unresolved_channel"
    ZERO_VALUE_TRANSACTION = "zero_value_transaction"
    #: A £0.00 payment KEPT because it carries item lines — a real order served
    #: at no charge, not a no-sale. Reported so the retention is visible.
    ZERO_VALUE_ORDER_RETAINED = "zero_value_order_retained"
    AMBIGUOUS_LOCAL_TIME = "ambiguous_local_time"
    NONEXISTENT_LOCAL_TIME = "nonexistent_local_time"
    UNKNOWN_TIME_ZONE = "unknown_time_zone"
    UNPARSABLE_MONEY = "unparsable_money"
    UNPARSABLE_QUANTITY = "unparsable_quantity"
    UNKNOWN_EVENT_TYPE = "unknown_event_type"
    MISSING_TRANSACTION_ID = "missing_transaction_id"
    ORPHAN_ITEM = "orphan_item"
    #: The order already exists from an earlier import (overlapping window).
    DUPLICATE_ORDER = "duplicate_order"
    REFUND_CHANNEL_INHERITED = "refund_channel_inherited"
    REFUND_CHANNEL_DERIVED = "refund_channel_derived"
    REFUND_CHANNEL_UNKNOWN = "refund_channel_unknown"


class Severity(str, Enum):
    #: The row is not normalised. It contributes to rows_skipped.
    SKIP = "skip"
    #: The row IS normalised, but something about it should be recorded.
    WARN = "warn"


@dataclass(frozen=True)
class RowIssue:
    """One row-level validation outcome, reportable back to the user."""

    row_number: int
    code: IssueCode
    severity: Severity
    message: str
    field: str | None = None
    #: Source identifier where known. Never contains customer or staff data.
    source_order_id: str | None = None

    def __str__(self) -> str:
        where = f" ({self.field})" if self.field else ""
        return f"row {self.row_number}{where}: {self.code.value} — {self.message}"


@dataclass
class ParseResult:
    """Everything one file yielded: canonical records plus an audit trail."""

    role: ImportFileRole
    path: Path
    rows_read: int = 0
    orders: list = field(default_factory=list)
    items: list = field(default_factory=list)
    summary_rows: list = field(default_factory=list)
    issues: list[RowIssue] = field(default_factory=list)
    #: Rows whose fate cannot be decided from this file alone. A £0.00 payment
    #: is a no-sale if nothing was served and a real order if something was,
    #: and only the ITEMS file knows which — so the decision is deferred until
    #: both have been read. See `resolve_zero_value_orders`.
    zero_value_candidates: list = field(default_factory=list)

    @property
    def rows_skipped(self) -> int:
        return sum(1 for i in self.issues if i.severity is Severity.SKIP)

    @property
    def rows_normalised(self) -> int:
        return len(self.orders) + len(self.items) + len(self.summary_rows)

    def issues_by_code(self) -> dict[IssueCode, int]:
        counts: dict[IssueCode, int] = {}
        for issue in self.issues:
            counts[issue.code] = counts.get(issue.code, 0) + 1
        return counts


class SourceAdapter(ABC):
    """Maps one external export format into canonical records.

    Implementations must not depend on SQLAlchemy or touch the database: an
    adapter reads files and returns canonical objects. Persistence is a
    separate concern layered on top.
    """

    #: Value written to Order.source for records this adapter produces.
    source_name: str

    @abstractmethod
    def read(self, path: Path, role: ImportFileRole) -> ParseResult:
        """Read one file in a known role and return canonical records."""
