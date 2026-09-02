"""Import orchestration: normalised Square records into PostgreSQL.

Responsibilities, in order:

  1. Checksum every supplied file.
  2. Parse and normalise them (no database contact yet).
  3. Preflight the checksums against import_files BEFORE anything is written.
  4. Persist batch, files, products, orders and items in ONE transaction.
  5. Reconcile against the Items Summary; fail the import if it does not match.

Failure semantics
-----------------
Two requirements pull against each other: "either everything succeeds or all
sales-data changes roll back", and "leave a clear failed status/error log".
A single transaction cannot do both — rolling back would erase the failure
record along with everything else.

So a processing failure is handled in two phases: the sales transaction rolls
back completely, then a SECOND, independent transaction writes an ImportBatch
with status=FAILED and a populated error_log.

A FAILED ImportBatch therefore has a precise meaning: **the import passed
preflight, began processing, and then failed.** A preflight rejection is not a
failed import — it is an operation that never started, and it creates no batch
at all. Conflating the two would fill the batch table with rows for imports
that never touched the data.

The failure record deliberately carries NO ImportFile rows. Checksums are
unique in import_files, so recording them against a failed batch would make the
import permanently un-retryable — a transient failure would poison the files
forever. The filenames and checksums are written into error_log instead, where
they are auditable but not constraining.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.adapters.base import IssueCode, ParseResult, RowIssue, Severity, SourceError
from app.adapters.parsing import parse_money_to_pence
from app.adapters.square import SquareAdapter, attach_items
from app.config import BUSINESS_TZ, UTC
from app.models import (
    ImportBatch,
    ImportFile,
    ImportStatus,
    Order,
    OrderItem,
    Product,
)
from app.models.enums import ImportFileRole
from app.schemas.canonical import CanonicalOrder, CanonicalOrderItem

CHECKSUM_CHUNK = 1024 * 1024


class ImportError_(Exception):
    """Base class for import failures. Carries the failed batch id when one
    was recorded."""

    def __init__(self, message: str, batch_id: int | None = None) -> None:
        super().__init__(message)
        self.batch_id = batch_id


class ImportRejected(ImportError_):
    """Preflight rejected the import; nothing was written to sales tables."""


class ReconciliationError(ImportError_):
    """Imported totals do not match the Items Summary exactly."""


class ConflictingOrderError(ImportError_):
    """An incoming order exists already with DIFFERENT content.

    Square considers a transaction immutable once settled, so this means the
    two extractions genuinely disagree. Silently keeping either version would
    leave the database holding data that matches no source file, so the import
    fails and rolls back instead.
    """


def file_checksum(path: Path) -> str:
    """SHA-256 of the file's bytes.

    Hashes raw bytes rather than parsed content: a byte-identical re-upload is
    what idempotency is defending against, and it costs nothing to detect.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHECKSUM_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ImportRequest:
    transactions: Path
    items: Path
    summary: Path | None = None
    label: str | None = None

    def as_mapping(self) -> dict[ImportFileRole, Path]:
        mapping = {
            ImportFileRole.TRANSACTIONS: self.transactions,
            ImportFileRole.ITEMS_DETAIL: self.items,
        }
        if self.summary is not None:
            mapping[ImportFileRole.ITEMS_SUMMARY] = self.summary
        return mapping


@dataclass
class Reconciliation:
    """Three independent checks against Square's own aggregation.

    The Items Summary is never imported — it is an oracle produced by Square's
    aggregation logic, used to verify ours (ARCHITECTURE.md §4).
    """

    performed: bool = False
    net_sales_ours: int = 0
    net_sales_theirs: int = 0
    line_totals_ours: int = 0
    line_totals_theirs: int = 0
    units_ours: int = 0
    units_theirs: int = 0

    @property
    def matches(self) -> bool:
        return (
            not self.performed
            or (
                self.net_sales_ours == self.net_sales_theirs
                and self.line_totals_ours == self.line_totals_theirs
                and self.units_ours == self.units_theirs
            )
        )

    def describe(self) -> str:
        return (
            f"net_sales ours={self.net_sales_ours} theirs={self.net_sales_theirs}; "
            f"line_totals ours={self.line_totals_ours} theirs={self.line_totals_theirs}; "
            f"units ours={self.units_ours} theirs={self.units_theirs}"
        )


@dataclass
class ImportOutcome:
    batch_id: int
    status: ImportStatus
    label: str | None
    period_start: date | None
    period_end: date | None
    orders_created: int = 0
    order_items_created: int = 0
    products_created: int = 0
    products_reused: int = 0
    rows_skipped: int = 0
    #: Integer pence. Computed regardless of whether reconciliation ran.
    net_sales_pence: int = 0
    reconciliation: Reconciliation = field(default_factory=Reconciliation)
    issues: list[RowIssue] = field(default_factory=list)

    def issue_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.code.value] = counts.get(issue.code.value, 0) + 1
        return counts


class SquareImportService:
    """Imports one logical Square export set."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._adapter = SquareAdapter()

    # -- public ---------------------------------------------------------------

    def run(self, request: ImportRequest) -> ImportOutcome:
        files = request.as_mapping()
        checksums = {role: file_checksum(path) for role, path in files.items()}

        try:
            with self._session_factory() as session, session.begin():
                # Preflight FIRST: a duplicate is decided by checksum alone, so
                # there is no reason to parse ~10 MB of UTF-16 to find out. It
                # also keeps the check and the insert in one transaction, so
                # two concurrent submissions cannot both pass.
                self._preflight(session, checksums)
                parsed = {
                    role: self._adapter.read(path, role) for role, path in files.items()
                }
                return self._persist(session, request, files, checksums, parsed)
        except ImportRejected:
            # Preflight rejection: the operation never started, so no batch is
            # created. A FAILED batch means "began processing, then failed".
            raise
        except (SourceError, ImportError_) as exc:
            batch_id = self._record_failure(request, files, checksums, exc)
            # Re-raise the ORIGINAL exception type, annotated with the batch id.
            # Wrapping it would erase the distinction between "this is not a
            # Square file" and "this import failed", which callers must map to
            # different responses.
            exc.batch_id = batch_id  # type: ignore[attr-defined]
            raise

    # -- preflight ------------------------------------------------------------

    def _preflight(self, session: Session, checksums: dict[ImportFileRole, str]) -> None:
        """Reject the whole import if ANY supplied file was already ingested.

        Runs before the batch row is created, so a rejected import leaves no
        orphaned batch and no partially-written sales data.
        """
        already = session.scalars(
            select(ImportFile).where(ImportFile.file_checksum.in_(checksums.values()))
        ).all()
        if not already:
            return

        by_checksum = {f.file_checksum: f for f in already}
        details = [
            f"{role.value} file {checksum[:12]}… was already ingested as "
            f"{by_checksum[checksum].filename!r} in batch "
            f"{by_checksum[checksum].import_batch_id}"
            for role, checksum in checksums.items()
            if checksum in by_checksum
        ]
        raise ImportRejected(
            "import rejected: " + "; ".join(details) + ". No data was written."
        )

    # -- persistence ----------------------------------------------------------

    def _persist(
        self,
        session: Session,
        request: ImportRequest,
        files: dict[ImportFileRole, Path],
        checksums: dict[ImportFileRole, str],
        parsed: dict[ImportFileRole, ParseResult],
    ) -> ImportOutcome:
        tx_result = parsed[ImportFileRole.TRANSACTIONS]
        item_result = parsed[ImportFileRole.ITEMS_DETAIL]
        summary_result = parsed.get(ImportFileRole.ITEMS_SUMMARY)

        orders, orphan_issues = attach_items(tx_result.orders, item_result.items)
        issues: list[RowIssue] = [
            *tx_result.issues,
            *item_result.issues,
            *orphan_issues,
        ]

        # Row-level dedup against orders already in the database. The unique
        # constraint on (source, source_order_id) is the backstop; this check
        # is what turns an overlapping extraction window into a reported skip
        # rather than a failed import.
        items_by_order: dict[str, list[CanonicalOrderItem]] = defaultdict(list)
        for line in item_result.items:
            items_by_order[line.source_order_id].append(line)

        orders, duplicate_issues = self._resolve_existing_orders(
            session, orders, items_by_order
        )
        issues.extend(duplicate_issues)

        keep = {o.source_order_id for o in orders}
        items = [i for i in item_result.items if i.source_order_id in keep]

        batch = ImportBatch(
            label=request.label,
            status=ImportStatus.PROCESSING,
            period_start=_period_bound(orders, min),
            period_end=_period_bound(orders, max),
        )
        session.add(batch)
        session.flush()

        product_ids, created, reused = self._upsert_products(session, items)

        order_ids = self._insert_orders(session, batch, orders)
        self._insert_items(session, order_ids, product_ids, items)

        reconciliation = self._reconcile(orders, items, summary_result)
        if not reconciliation.matches:
            raise ReconciliationError(
                "reconciliation against Items Summary failed: "
                + reconciliation.describe()
            )

        self._record_files(
            session, batch, files, checksums, parsed, len(orders), len(items)
        )

        batch.status = ImportStatus.COMPLETED
        batch.error_log = _format_issues(issues) or None

        return ImportOutcome(
            batch_id=batch.id,
            status=ImportStatus.COMPLETED,
            label=batch.label,
            period_start=batch.period_start,
            period_end=batch.period_end,
            orders_created=len(orders),
            order_items_created=len(items),
            products_created=created,
            products_reused=reused,
            rows_skipped=sum(1 for i in issues if i.severity is Severity.SKIP),
            net_sales_pence=sum(o.net_amount for o in orders),
            reconciliation=reconciliation,
            issues=issues,
        )

    def _resolve_existing_orders(
        self,
        session: Session,
        orders: list[CanonicalOrder],
        items_by_order: dict[str, list[CanonicalOrderItem]],
    ) -> tuple[list[CanonicalOrder], list[RowIssue]]:
        """Compare incoming orders against any already-persisted version.

        An overlapping extraction window legitimately re-supplies orders we
        already hold. Blindly skipping them would be wrong: if the two versions
        DIFFER, the database is holding a record that matches no source file,
        and quietly preserving the stale one hides a genuine data problem.

        So each collision is classified:

          * byte-for-byte equivalent  -> safe duplicate, skipped and reported
          * different in any field    -> ConflictingOrderError, import rolls back

        The unique constraint on (source, source_order_id) remains the final
        concurrency backstop beneath this check.
        """
        if not orders:
            return [], []

        keys = {(o.source, o.source_order_id) for o in orders}
        existing = {
            (o.source, o.source_order_id): o
            for o in session.scalars(
                select(Order)
                .where(tuple_(Order.source, Order.source_order_id).in_(keys))
                .options(selectinload(Order.items).selectinload(OrderItem.product))
            ).all()
        }
        if not existing:
            return orders, []

        kept: list[CanonicalOrder] = []
        issues: list[RowIssue] = []
        conflicts: list[str] = []

        for order in orders:
            persisted = existing.get((order.source, order.source_order_id))
            if persisted is None:
                kept.append(order)
                continue

            incoming = _incoming_fingerprint(
                order, items_by_order.get(order.source_order_id, [])
            )
            stored = _persisted_fingerprint(persisted)

            if incoming == stored:
                issues.append(
                    RowIssue(
                        0,
                        IssueCode.DUPLICATE_ORDER,
                        Severity.SKIP,
                        "identical order already present from an earlier import "
                        "(overlapping extraction window)",
                        "Transaction ID",
                        order.source_order_id,
                    )
                )
                continue

            conflicts.append(
                f"{order.source_order_id}: "
                + "; ".join(_describe_differences(incoming, stored))
            )

        if conflicts:
            raise ConflictingOrderError(
                f"{len(conflicts)} order(s) already exist with different content, "
                "so the extractions disagree. Import rolled back rather than "
                "keeping stale data. "
                + " | ".join(conflicts[:5])
            )

        return kept, issues

    def _upsert_products(
        self, session: Session, items: list[CanonicalOrderItem]
    ) -> tuple[dict[tuple[str, str], int], int, int]:
        wanted = {i.product.key: i.product for i in items}
        if not wanted:
            return {}, 0, 0

        existing = session.scalars(
            select(Product).where(Product.name.in_({k[0] for k in wanted}))
        ).all()
        ids = {(p.name, p.variation): p.id for p in existing if (p.name, p.variation) in wanted}
        reused = len(ids)

        new_products = [
            Product(
                name=product.name,
                variation=product.variation,
                category=product.category,
                kind=product.kind,
            )
            for key, product in wanted.items()
            if key not in ids
        ]
        # An existing product keeps its stored `kind`: the catalogue is the
        # authority once a product exists, and a heuristic re-classification
        # should never silently rewrite it.
        session.add_all(new_products)
        session.flush()
        ids.update({(p.name, p.variation): p.id for p in new_products})
        return ids, len(new_products), reused

    def _insert_orders(
        self, session: Session, batch: ImportBatch, orders: list[CanonicalOrder]
    ) -> dict[str, int]:
        rows = [
            Order(
                source=o.source,
                source_order_id=o.source_order_id,
                source_payment_id=o.source_payment_id,
                occurred_at=o.occurred_at,
                channel=o.channel,
                event_type=o.event_type,
                gross_amount=o.gross_amount,
                discount_amount=o.discount_amount,
                net_amount=o.net_amount,
                item_count=o.item_count,
                import_batch_id=batch.id,
            )
            for o in orders
        ]
        session.add_all(rows)
        session.flush()
        return {r.source_order_id: r.id for r in rows}

    def _insert_items(
        self,
        session: Session,
        order_ids: dict[str, int],
        product_ids: dict[tuple[str, str], int],
        items: list[CanonicalOrderItem],
    ) -> None:
        session.add_all(
            [
                OrderItem(
                    order_id=order_ids[i.source_order_id],
                    product_id=product_ids[i.product.key],
                    quantity=i.quantity,
                    unit_price=i.unit_price,
                    line_total=i.line_total,
                    discount_amount=i.discount_amount,
                )
                for i in items
            ]
        )
        session.flush()

    def _record_files(
        self,
        session: Session,
        batch: ImportBatch,
        files: dict[ImportFileRole, Path],
        checksums: dict[ImportFileRole, str],
        parsed: dict[ImportFileRole, ParseResult],
        orders_created: int,
        items_created: int,
    ) -> None:
        imported = {
            ImportFileRole.TRANSACTIONS: orders_created,
            ImportFileRole.ITEMS_DETAIL: items_created,
            # The summary is reconciliation-only: every row is read and none is
            # imported, so all of them count as skipped.
            ImportFileRole.ITEMS_SUMMARY: 0,
        }
        for role, path in files.items():
            result = parsed[role]
            rows_imported = imported[role]
            session.add(
                ImportFile(
                    import_batch_id=batch.id,
                    role=role,
                    filename=path.name,
                    file_checksum=checksums[role],
                    row_count=result.rows_read,
                    rows_imported=rows_imported,
                    rows_skipped=result.rows_read - rows_imported,
                )
            )
        session.flush()

    # -- reconciliation -------------------------------------------------------

    def _reconcile(
        self,
        orders: list[CanonicalOrder],
        items: list[CanonicalOrderItem],
        summary: ParseResult | None,
    ) -> Reconciliation:
        report = Reconciliation()
        if summary is None or not summary.summary_rows:
            return report

        report.performed = True
        report.net_sales_ours = sum(o.net_amount for o in orders)
        report.line_totals_ours = sum(i.line_total for i in items)
        report.units_ours = sum(i.quantity for i in items)

        rows = summary.summary_rows
        report.net_sales_theirs = sum(parse_money_to_pence(r.net_sales) for r in rows)
        # Square records refunds and refunded units as NEGATIVE values, the same
        # convention as its Discounts column, so these are ADDED not subtracted.
        report.line_totals_theirs = sum(
            parse_money_to_pence(r.product_sales) + parse_money_to_pence(r.refunds)
            for r in rows
        )
        report.units_theirs = sum(
            int(r.units_sold or 0) + int(r.items_refunded or 0) for r in rows
        )
        return report

    # -- failure --------------------------------------------------------------

    def _record_failure(
        self,
        request: ImportRequest,
        files: dict[ImportFileRole, Path],
        checksums: dict[ImportFileRole, str],
        exc: Exception,
    ) -> int:
        """Write a FAILED batch in its own transaction, with no ImportFile rows.

        See the module docstring: recording the checksums here would make the
        import permanently un-retryable.
        """
        manifest = "\n".join(
            f"  {role.value}: {files[role].name} sha256={checksums[role]}"
            for role in files
        )
        with self._session_factory() as session, session.begin():
            batch = ImportBatch(
                label=request.label,
                status=ImportStatus.FAILED,
                error_log=(
                    f"{type(exc).__name__}: {exc}\n\nfiles supplied:\n{manifest}"
                ),
            )
            session.add(batch)
            session.flush()
            return batch.id


#: Field labels for the comparable fingerprint, used to explain a conflict.
_FINGERPRINT_FIELDS = (
    "occurred_at", "channel", "event_type", "gross_amount", "discount_amount",
    "net_amount", "item_count", "source_payment_id", "line_items",
)


def _line_fingerprint(lines) -> tuple:
    """Order-independent, comparable representation of an order's lines."""
    return tuple(sorted(lines))


def _incoming_fingerprint(
    order: CanonicalOrder, items: list[CanonicalOrderItem]
) -> tuple:
    return (
        order.occurred_at.astimezone(UTC),
        order.channel,
        order.event_type,
        order.gross_amount,
        order.discount_amount,
        order.net_amount,
        order.item_count,
        order.source_payment_id,
        _line_fingerprint(
            (i.product.name, i.product.variation, i.quantity, i.unit_price,
             i.line_total, i.discount_amount)
            for i in items
        ),
    )


def _persisted_fingerprint(order: Order) -> tuple:
    return (
        order.occurred_at.astimezone(UTC),
        order.channel,
        order.event_type,
        order.gross_amount,
        order.discount_amount,
        order.net_amount,
        order.item_count,
        order.source_payment_id,
        _line_fingerprint(
            (i.product.name, i.product.variation, i.quantity, i.unit_price,
             i.line_total, i.discount_amount)
            for i in order.items
        ),
    )


def _describe_differences(incoming: tuple, stored: tuple) -> list[str]:
    return [
        f"{name} incoming={new!r} stored={old!r}"
        for name, new, old in zip(_FINGERPRINT_FIELDS, incoming, stored)
        if new != old
    ]


def _period_bound(orders: list[CanonicalOrder], pick) -> date | None:
    """Inclusive calendar bound in the business's own timezone.

    Derived by converting each UTC instant back to Europe/London, not by
    truncating the UTC timestamp: 00:30 BST on 1 August is 23:30 UTC on
    31 July, and taking the UTC date would report coverage a day early.
    """
    if not orders:
        return None
    return pick(o.occurred_at.astimezone(BUSINESS_TZ).date() for o in orders)


def _format_issues(issues: list[RowIssue]) -> str:
    if not issues:
        return ""
    counts: dict[str, int] = {}
    for issue in issues:
        counts[issue.code.value] = counts.get(issue.code.value, 0) + 1
    lines = [f"{code}: {n}" for code, n in sorted(counts.items())]
    sample = [str(i) for i in issues[:20]]
    return "counts:\n  " + "\n  ".join(lines) + "\n\nfirst rows:\n  " + "\n  ".join(sample)
