"""Persistence and import orchestration."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from app.adapters.base import IssueCode
from app.analytics.service import AnalyticsService
from app.models import (
    ImportBatch,
    ImportFile,
    ImportStatus,
    Order,
    OrderItem,
    Product,
)
from app.models.enums import Channel, ImportFileRole, OrderEventType, ProductKind
from app.services.importer import (
    ConflictingOrderError,
    ImportRejected,
    ReconciliationError,
    SquareImportService,
    UnresolvedChannelError,
    file_checksum,
)
from tests.conftest import item_row, summary_row, transaction_row


def counts(session_factory) -> dict[str, int]:
    with session_factory() as s:
        return {
            "orders": s.scalar(select(func.count()).select_from(Order)),
            "items": s.scalar(select(func.count()).select_from(OrderItem)),
            "products": s.scalar(select(func.count()).select_from(Product)),
            "batches": s.scalar(select(func.count()).select_from(ImportBatch)),
            "files": s.scalar(select(func.count()).select_from(ImportFile)),
        }


def simple_import(square_files, label="b1", tx_id="TX-1", with_summary=True):
    """One order, two lines (£3.65 + £7.30 = £10.95), with a matching summary.

    `with_summary=False` is needed whenever two imports would otherwise supply
    byte-identical summary files — which preflight correctly rejects.
    """
    return square_files(
        transactions=[
            transaction_row(**{"Transaction ID": tx_id, "Payment ID": f"PAY-{tx_id}",
                               "Gross Sales": "£10.95", "Net Sales": "£10.95"})
        ],
        items=[
            item_row(**{"Transaction ID": tx_id, "Item": "Caffe Latte",
                        "Price Point Name": "Regular", "Qty": "1.0",
                        "Product Sales": "£3.65"}),
            item_row(**{"Transaction ID": tx_id, "Item": "Caffe Latte",
                        "Price Point Name": "Large", "Qty": "2.0",
                        "Product Sales": "£7.30"}),
        ],
        summary=[
            summary_row(**{"Item Variation": "Regular", "Units Sold": "1",
                           "Product Sales": "£3.65", "Net Sales": "£3.65"}),
            summary_row(**{"Item Variation": "Large", "Units Sold": "2",
                           "Product Sales": "£7.30", "Net Sales": "£7.30"}),
        ] if with_summary else None,
        label=label,
    )


# --- success -----------------------------------------------------------------


def test_successful_import_persists_everything(session_factory, square_files):
    service = SquareImportService(session_factory)
    outcome = service.run(simple_import(square_files))

    assert outcome.status is ImportStatus.COMPLETED
    assert outcome.orders_created == 1
    assert outcome.order_items_created == 2
    assert outcome.products_created == 2
    assert counts(session_factory) == {
        "orders": 1, "items": 2, "products": 2, "batches": 1, "files": 3
    }

    with session_factory() as s:
        order = s.scalar(select(Order))
        assert order.source == "square"
        assert order.source_order_id == "TX-1"
        assert order.net_amount == 1095
        assert order.channel is Channel.IN_STORE
        assert order.event_type is OrderEventType.PAYMENT
        assert order.item_count == 3
        assert order.import_batch_id == outcome.batch_id


def test_batch_records_period_label_and_status(session_factory, square_files):
    outcome = SquareImportService(session_factory).run(simple_import(square_files))
    with session_factory() as s:
        batch = s.get(ImportBatch, outcome.batch_id)
        assert batch.status is ImportStatus.COMPLETED
        assert batch.label == "b1"
        assert batch.period_start == date(2026, 8, 15)
        assert batch.period_end == date(2026, 8, 15)


def test_one_import_file_row_per_supplied_file(session_factory, square_files):
    request = simple_import(square_files)
    SquareImportService(session_factory).run(request)
    with session_factory() as s:
        files = {f.role: f for f in s.scalars(select(ImportFile)).all()}
    assert set(files) == set(ImportFileRole)
    assert files[ImportFileRole.TRANSACTIONS].file_checksum == file_checksum(
        request.transactions
    )
    assert files[ImportFileRole.TRANSACTIONS].rows_imported == 1
    assert files[ImportFileRole.ITEMS_DETAIL].rows_imported == 2
    # Summary is reconciliation-only: read, never imported.
    assert files[ImportFileRole.ITEMS_SUMMARY].rows_imported == 0
    assert files[ImportFileRole.ITEMS_SUMMARY].rows_skipped == 2


def test_import_without_a_summary_is_allowed(session_factory, square_files):
    request = square_files(
        transactions=[transaction_row(**{"Net Sales": "£3.65", "Gross Sales": "£3.65"})],
        items=[item_row()],
        summary=None,
    )
    outcome = SquareImportService(session_factory).run(request)
    assert outcome.status is ImportStatus.COMPLETED
    assert outcome.reconciliation.performed is False
    assert counts(session_factory)["files"] == 2


# --- products ----------------------------------------------------------------


def test_products_are_reused_across_orders_and_imports(session_factory, square_files):
    service = SquareImportService(session_factory)
    service.run(simple_import(square_files, label="b1", tx_id="TX-1"))
    # No summary on the second run: an identical summary file would be
    # rejected by preflight, which is itself correct behaviour.
    outcome = service.run(
        simple_import(square_files, label="b2", tx_id="TX-2", with_summary=False)
    )

    assert outcome.products_created == 0
    assert outcome.products_reused == 2
    assert counts(session_factory)["products"] == 2      # not 4
    assert counts(session_factory)["orders"] == 2


def test_product_kind_is_preserved(session_factory, square_files):
    request = square_files(
        transactions=[transaction_row(**{"Net Sales": "£10.00", "Gross Sales": "£10.00"})],
        items=[
            item_row(**{"Item": "TCL - £10.00 Gift Voucher", "Category": "Uncategorised",
                        "Product Sales": "£10.00"}),
        ],
    )
    SquareImportService(session_factory).run(request)
    with session_factory() as s:
        product = s.scalar(select(Product))
        assert product.kind is ProductKind.GIFT_VOUCHER


def test_variation_distinguishes_products(session_factory, square_files):
    SquareImportService(session_factory).run(simple_import(square_files))
    with session_factory() as s:
        keys = {(p.name, p.variation) for p in s.scalars(select(Product)).all()}
    assert keys == {("Caffe Latte", "Regular"), ("Caffe Latte", "Large")}


# --- duplicate files ---------------------------------------------------------


def test_reimporting_the_same_files_is_rejected(session_factory, square_files):
    service = SquareImportService(session_factory)
    request = simple_import(square_files)
    service.run(request)

    before = counts(session_factory)
    with pytest.raises(ImportRejected, match="already ingested"):
        service.run(request)

    after = counts(session_factory)
    assert after["orders"] == before["orders"]
    assert after["items"] == before["items"]
    assert after["files"] == before["files"]


def test_preflight_rejection_creates_no_import_batch_at_all(
    session_factory, square_files
):
    """A preflight rejection is an operation that never started — not a failed
    import. A FAILED batch means processing began and then failed."""
    service = SquareImportService(session_factory)
    request = simple_import(square_files)
    service.run(request)

    before = counts(session_factory)["batches"]
    with pytest.raises(ImportRejected) as exc:
        service.run(request)

    assert exc.value.batch_id is None
    assert counts(session_factory)["batches"] == before      # unchanged
    with session_factory() as s:
        assert s.scalar(
            select(func.count()).select_from(ImportBatch).where(
                ImportBatch.status == ImportStatus.FAILED
            )
        ) == 0


def test_partial_overlap_rejects_the_whole_import(session_factory, square_files, tmp_path):
    """One shared file is enough: the import is atomic, not per-file."""
    service = SquareImportService(session_factory)
    first = simple_import(square_files, label="b1", tx_id="TX-1")
    service.run(first)

    second = simple_import(square_files, label="b2", tx_id="TX-2", with_summary=False)
    reused = type(second)(
        transactions=first.transactions,   # already ingested
        items=second.items,                # new
        summary=None,
        label="b3",
    )
    with pytest.raises(ImportRejected):
        service.run(reused)
    assert counts(session_factory)["orders"] == 1


# --- overlapping order ids ---------------------------------------------------


def _tx1_rows():
    """The exact transaction + item rows the first import used for TX-1."""
    return (
        transaction_row(**{"Transaction ID": "TX-1", "Payment ID": "PAY-TX-1",
                           "Gross Sales": "£10.95", "Net Sales": "£10.95"}),
        [
            item_row(**{"Transaction ID": "TX-1", "Item": "Caffe Latte",
                        "Price Point Name": "Regular", "Qty": "1.0",
                        "Product Sales": "£3.65"}),
            item_row(**{"Transaction ID": "TX-1", "Item": "Caffe Latte",
                        "Price Point Name": "Large", "Qty": "2.0",
                        "Product Sales": "£7.30"}),
        ],
    )


def test_identical_overlapping_order_is_skipped_as_a_safe_duplicate(
    session_factory, square_files
):
    """Different files (new checksums) whose windows overlap on TX-1, where the
    re-supplied TX-1 is byte-for-byte equivalent to the persisted one."""
    service = SquareImportService(session_factory)
    service.run(simple_import(square_files, label="b1", tx_id="TX-1"))

    tx1, tx1_items = _tx1_rows()
    overlapping = square_files(
        transactions=[
            tx1,
            transaction_row(**{"Transaction ID": "TX-NEW", "Payment ID": "PAY-NEW",
                               "Gross Sales": "£3.65", "Net Sales": "£3.65"}),
        ],
        items=[*tx1_items,
               item_row(**{"Transaction ID": "TX-NEW", "Product Sales": "£3.65"})],
        label="b2",
    )
    outcome = service.run(overlapping)

    assert outcome.status is ImportStatus.COMPLETED
    assert outcome.orders_created == 1                     # only TX-NEW
    assert IssueCode.DUPLICATE_ORDER in {i.code for i in outcome.issues}
    assert counts(session_factory)["orders"] == 2          # not 3
    assert counts(session_factory)["items"] == 3           # TX-1's lines not re-added

    with session_factory() as s:
        assert s.scalar(
            select(func.count()).select_from(Order).where(Order.source_order_id == "TX-1")
        ) == 1


def test_conflicting_version_of_an_existing_order_fails_the_import(
    session_factory, square_files
):
    """Square treats a settled transaction as immutable, so a differing version
    means the two extractions genuinely disagree. Keeping either silently would
    leave the database matching no source file."""
    service = SquareImportService(session_factory)
    service.run(simple_import(square_files, label="b1", tx_id="TX-1"))
    before = counts(session_factory)

    # SKU is never bound by our row schemas, so varying it changes the file's
    # checksum (clearing preflight) while leaving the canonical items identical.
    conflicting = square_files(
        transactions=[
            transaction_row(**{"Transaction ID": "TX-1", "Payment ID": "PAY-TX-1",
                               "Gross Sales": "£99.00", "Net Sales": "£99.00"}),
        ],
        items=[
            item_row(**{"Transaction ID": "TX-1", "Item": "Caffe Latte",
                        "Price Point Name": "Regular", "Qty": "1.0",
                        "Product Sales": "£3.65", "SKU": "RE-EXPORT"}),
            item_row(**{"Transaction ID": "TX-1", "Item": "Caffe Latte",
                        "Price Point Name": "Large", "Qty": "2.0",
                        "Product Sales": "£7.30", "SKU": "RE-EXPORT"}),
        ],
        label="b2",
    )
    with pytest.raises(ConflictingOrderError, match="TX-1") as exc:
        service.run(conflicting)

    # Nothing changed except a FAILED batch: this one DID pass preflight.
    after = counts(session_factory)
    assert after["orders"] == before["orders"]
    assert after["items"] == before["items"]
    assert after["products"] == before["products"]
    assert after["files"] == before["files"]
    assert after["batches"] == before["batches"] + 1

    with session_factory() as s:
        failed = s.get(ImportBatch, exc.value.batch_id)
        assert failed.status is ImportStatus.FAILED
        assert "net_amount" in failed.error_log
        assert failed.files == []
        # The persisted order is untouched and still matches the first import.
        assert s.scalar(
            select(Order.net_amount).where(Order.source_order_id == "TX-1")
        ) == 1095


def test_conflicting_line_items_also_fail_the_import(session_factory, square_files):
    """The order header can match while the lines differ."""
    service = SquareImportService(session_factory)
    service.run(simple_import(square_files, label="b1", tx_id="TX-1"))

    conflicting = square_files(
        transactions=[
            transaction_row(**{"Transaction ID": "TX-1", "Payment ID": "PAY-TX-1",
                               "Gross Sales": "£10.95", "Net Sales": "£10.95",
                               # Ignored column: changes the checksum, not the data.
                               "Customer Name": "Re-export"}),
        ],
        items=[
            item_row(**{"Transaction ID": "TX-1", "Item": "Flat White",
                        "Price Point Name": "Regular", "Qty": "1.0",
                        "Product Sales": "£3.65"}),
            item_row(**{"Transaction ID": "TX-1", "Item": "Caffe Latte",
                        "Price Point Name": "Large", "Qty": "2.0",
                        "Product Sales": "£7.30"}),
        ],
        label="b2",
    )
    with pytest.raises(ConflictingOrderError, match="line_items"):
        service.run(conflicting)
    assert counts(session_factory)["orders"] == 1


def test_unique_constraint_is_the_backstop(session_factory, square_files):
    """The database constraint holds regardless of the service's own check."""
    from sqlalchemy.exc import IntegrityError

    SquareImportService(session_factory).run(simple_import(square_files))
    with session_factory() as s:
        s.add(Order(source="square", source_order_id="TX-1",
                    occurred_at=s.scalar(select(Order.occurred_at)),
                    channel=Channel.IN_STORE, event_type=OrderEventType.PAYMENT,
                    gross_amount=1, discount_amount=0, net_amount=1, item_count=1))
        with pytest.raises(IntegrityError, match="uq_orders_source_order"):
            s.commit()


# --- reconciliation ----------------------------------------------------------


def test_reconciliation_matches_on_a_good_import(session_factory, square_files):
    outcome = SquareImportService(session_factory).run(simple_import(square_files))
    r = outcome.reconciliation
    assert r.performed and r.matches
    assert r.net_sales_ours == r.net_sales_theirs == 1095
    assert r.line_totals_ours == r.line_totals_theirs == 1095
    assert r.units_ours == r.units_theirs == 3


def test_reconciliation_mismatch_fails_the_import(session_factory, square_files):
    request = square_files(
        transactions=[transaction_row(**{"Net Sales": "£3.65", "Gross Sales": "£3.65"})],
        items=[item_row(**{"Product Sales": "£3.65"})],
        summary=[summary_row(**{"Units Sold": "99", "Product Sales": "£99.00",
                                "Net Sales": "£99.00"})],
    )
    with pytest.raises(ReconciliationError, match="reconciliation"):
        SquareImportService(session_factory).run(request)


def test_reconciliation_accounts_for_negative_refund_columns(session_factory, square_files):
    """Square stores Refunds and Items Refunded as NEGATIVE values."""
    request = square_files(
        transactions=[
            transaction_row(**{"Transaction ID": "TX-P", "Payment ID": "PAY-1",
                               "Net Sales": "£3.65", "Gross Sales": "£3.65"}),
            transaction_row(**{"Transaction ID": "TX-R", "Payment ID": "PAY-1",
                               "Event Type": "Refund", "Dining Option": "",
                               "Net Sales": "-£3.65", "Gross Sales": "-£3.65"}),
        ],
        items=[
            item_row(**{"Transaction ID": "TX-P", "Qty": "1.0", "Product Sales": "£3.65"}),
            item_row(**{"Transaction ID": "TX-R", "Qty": "-1.0", "Product Sales": "-£3.65"}),
        ],
        summary=[summary_row(**{"Units Sold": "1", "Items Refunded": "-1",
                                "Product Sales": "£3.65", "Refunds": "-£3.65",
                                "Net Sales": "£0.00"})],
    )
    outcome = SquareImportService(session_factory).run(request)
    assert outcome.reconciliation.matches
    assert outcome.reconciliation.units_ours == 0
    assert outcome.reconciliation.net_sales_ours == 0


# --- rollback ----------------------------------------------------------------


def test_failed_reconciliation_leaves_no_sales_data(session_factory, square_files):
    request = square_files(
        transactions=[transaction_row(**{"Net Sales": "£3.65", "Gross Sales": "£3.65"})],
        items=[item_row(**{"Product Sales": "£3.65"})],
        summary=[summary_row(**{"Units Sold": "99", "Product Sales": "£99.00",
                                "Net Sales": "£99.00"})],
    )
    with pytest.raises(ReconciliationError) as exc:
        SquareImportService(session_factory).run(request)

    result = counts(session_factory)
    assert result["orders"] == 0
    assert result["items"] == 0
    assert result["products"] == 0        # products rolled back too
    assert result["files"] == 0
    assert result["batches"] == 1         # only the FAILED record

    with session_factory() as s:
        batch = s.get(ImportBatch, exc.value.batch_id)
        assert batch.status is ImportStatus.FAILED
        assert "reconciliation" in batch.error_log
        assert "sha256=" in batch.error_log      # manifest for audit


def test_a_failed_import_can_be_retried_after_the_cause_is_fixed(
    session_factory, square_files
):
    """The failure record holds no ImportFile rows, so checksums stay usable."""
    bad = square_files(
        transactions=[transaction_row(**{"Net Sales": "£3.65", "Gross Sales": "£3.65"})],
        items=[item_row(**{"Product Sales": "£3.65"})],
        summary=[summary_row(**{"Units Sold": "99", "Product Sales": "£99.00",
                                "Net Sales": "£99.00"})],
        label="retry",
    )
    service = SquareImportService(session_factory)
    with pytest.raises(ReconciliationError):
        service.run(bad)

    # Same transactions/items files, corrected summary.
    fixed = type(bad)(
        transactions=bad.transactions, items=bad.items,
        summary=square_files(
            transactions=[], items=[],
            summary=[summary_row(**{"Units Sold": "1", "Product Sales": "£3.65",
                                    "Net Sales": "£3.65"})],
            label="fixed",
        ).summary,
        label="retry-2",
    )
    outcome = service.run(fixed)
    assert outcome.status is ImportStatus.COMPLETED
    assert counts(session_factory)["orders"] == 1


def test_malformed_file_fails_before_writing_sales_data(session_factory, square_files, tmp_path):
    from app.adapters.base import SourceFormatError
    from app.services.importer import ImportError_
    from tests.conftest import TRANSACTION_COLUMNS, write_square_export

    good = simple_import(square_files, label="ok")
    bad_tx = write_square_export(
        tmp_path / "bad.csv", TRANSACTION_COLUMNS,
        [transaction_row()], encoding="utf-8",
    )
    request = type(good)(transactions=bad_tx, items=good.items,
                         summary=good.summary, label="bad")

    with pytest.raises((SourceFormatError, ImportError_)):
        SquareImportService(session_factory).run(request)

    result = counts(session_factory)
    assert result["orders"] == 0 and result["items"] == 0 and result["files"] == 0


# --- refunds and skipped rows ------------------------------------------------


def test_refunds_are_persisted_with_event_type_and_payment_id(
    session_factory, square_files
):
    request = square_files(
        transactions=[
            transaction_row(**{"Transaction ID": "TX-P", "Payment ID": "PAY-9",
                               "Source": "Deliveroo", "Dining Option": "",
                               "Net Sales": "£10.00", "Gross Sales": "£10.00"}),
            transaction_row(**{"Transaction ID": "TX-R", "Payment ID": "PAY-9",
                               "Source": "Register", "Dining Option": "",
                               "Event Type": "Refund",
                               "Net Sales": "-£10.00", "Gross Sales": "-£10.00"}),
        ],
        items=[item_row(**{"Transaction ID": "TX-P", "Product Sales": "£10.00"})],
    )
    SquareImportService(session_factory).run(request)

    with session_factory() as s:
        orders = {o.source_order_id: o for o in s.scalars(select(Order)).all()}
        assert orders["TX-R"].event_type is OrderEventType.REFUND
        assert orders["TX-R"].net_amount == -1000
        assert orders["TX-R"].channel is Channel.DELIVERY       # inherited
        assert orders["TX-P"].source_payment_id == orders["TX-R"].source_payment_id
        # Revenue nets out; order COUNT excludes the refund.
        assert s.scalar(select(func.sum(Order.net_amount))) == 0
        assert s.scalar(
            select(func.count()).select_from(Order).where(
                Order.event_type == OrderEventType.PAYMENT
            )
        ) == 1


def test_skipped_rows_are_counted_on_the_import_file(session_factory, square_files):
    """A zero-value no-sale is still skipped and still counted.

    This is the deliberate exclusion and it is unchanged: a £0.00 payment with
    no discount is not analytical revenue. It is reported, not hidden.
    """
    request = square_files(
        transactions=[
            transaction_row(**{"Transaction ID": "TX-OK", "Net Sales": "£3.65",
                               "Gross Sales": "£3.65"}),
            transaction_row(**{"Transaction ID": "TX-ZERO", "Net Sales": "£0.00",
                               "Gross Sales": "£0.00"}),
        ],
        items=[item_row(**{"Transaction ID": "TX-OK", "Product Sales": "£3.65"})],
    )
    outcome = SquareImportService(session_factory).run(request)

    assert outcome.orders_created == 1
    with session_factory() as s:
        tx_file = s.scalar(
            select(ImportFile).where(ImportFile.role == ImportFileRole.TRANSACTIONS)
        )
        assert tx_file.row_count == 2
        assert tx_file.rows_imported == 1
        assert tx_file.rows_skipped == 1
        batch = s.get(ImportBatch, outcome.batch_id)
        assert "zero_value_transaction" in batch.error_log


# --- unresolved channels -----------------------------------------------------
#
# A transaction whose channel cannot be derived used to be skipped like any
# other unnormalisable row. Its item lines went with it, and the loss only
# surfaced much later as a reconciliation mismatch against Square's Items
# Summary — which counts every sold item however it was fulfilled. The failure
# named the wrong layer. It now stops the import before anything is written.


def unresolved_import(square_files, **overrides):
    """One good order plus one whose Source/Dining Option cannot be mapped."""
    bad = {"Transaction ID": "TX-BAD", "Payment ID": "PAY-BAD",
           "Net Sales": "£5.00", "Gross Sales": "£5.00"}
    bad.update(overrides)
    return square_files(
        transactions=[
            transaction_row(**{"Transaction ID": "TX-OK", "Payment ID": "PAY-OK",
                               "Net Sales": "£3.65", "Gross Sales": "£3.65"}),
            transaction_row(**bad),
        ],
        items=[
            item_row(**{"Transaction ID": "TX-OK", "Product Sales": "£3.65"}),
            item_row(**{"Transaction ID": "TX-BAD", "Item": "Mystery Item",
                        "Product Sales": "£5.00"}),
        ],
    )


@pytest.mark.parametrize(
    "overrides,expected_fragment",
    [
        ({"Source": "Mystery Co"}, "unmapped source"),
        ({"Dining Option": "Kerbside"}, "unmapped dining option"),
        ({"Dining Option": ""}, "no dining option"),
    ],
)
def test_unresolvable_channel_rejects_the_import(
    session_factory, square_files, overrides, expected_fragment
):
    """An unmapped combination fails as ITSELF, not as a reconciliation error.

    The distinction is the whole point: reconciliation_failed sends the reader
    to look for an arithmetic bug in a source file that is perfectly correct.
    """
    service = SquareImportService(session_factory)

    with pytest.raises(UnresolvedChannelError) as caught:
        service.run(unresolved_import(square_files, **overrides))

    message = str(caught.value)
    assert expected_fragment in message
    # Enough context to extend the mapping without opening the file.
    assert "TX-BAD" in message
    assert "row" in message


def test_unresolvable_channel_writes_no_sales_data(session_factory, square_files):
    """Atomicity: the good order in the same file is not written either."""
    before = counts(session_factory)

    with pytest.raises(UnresolvedChannelError):
        SquareImportService(session_factory).run(
            unresolved_import(square_files, **{"Source": "Mystery Co"})
        )

    after = counts(session_factory)
    assert after["orders"] == before["orders"] == 0
    assert after["items"] == before["items"] == 0
    assert after["products"] == before["products"] == 0
    # The FAILED batch IS recorded — that is how a failure stays diagnosable —
    # but it carries no ImportFile rows, so the checksums remain retryable.
    assert after["batches"] == before["batches"] + 1
    assert after["files"] == before["files"] == 0


def test_unresolvable_channel_is_not_reported_as_reconciliation_failure(
    session_factory, square_files
):
    """The regression this exists for.

    Before the fix the unresolvable order was dropped, its items were dropped
    with it, and the import died complaining that our totals disagreed with
    Square's — 5 units and £32.70 short, in the real September export.
    """
    with pytest.raises(UnresolvedChannelError):
        SquareImportService(session_factory).run(
            unresolved_import(square_files, **{"Dining Option": "Kerbside"})
        )


def test_a_refund_never_triggers_the_unresolved_channel_rejection(
    session_factory, square_files
):
    """A refund is a real financial event whichever way its columns read.

    It inherits its payment's channel, or is recorded as UNKNOWN — it is never
    dropped, so it can never be the thing that stops an import.
    """
    request = square_files(
        transactions=[
            transaction_row(**{"Transaction ID": "TX-P", "Payment ID": "PAY-1",
                               "Net Sales": "£10.00", "Gross Sales": "£10.00",
                               "Source": "Uber Eats", "Dining Option": ""}),
            transaction_row(**{"Transaction ID": "TX-R", "Payment ID": "PAY-1",
                               "Event Type": "Refund", "Net Sales": "-£10.00",
                               "Gross Sales": "-£10.00", "Source": "",
                               "Dining Option": ""}),
        ],
        items=[item_row(**{"Transaction ID": "TX-P", "Product Sales": "£10.00"})],
    )

    outcome = SquareImportService(session_factory).run(request)
    assert outcome.orders_created == 2


def test_mixed_fulfilment_combinations_import_successfully(
    session_factory, square_files
):
    """The two combinations found in the real year now import cleanly."""
    request = square_files(
        transactions=[
            transaction_row(**{"Transaction ID": "TX-A", "Payment ID": "PAY-A",
                               "Net Sales": "£5.00", "Gross Sales": "£5.00",
                               "Source": "Point of Sale",
                               "Dining Option": "Eat In, Pick Up"}),
            transaction_row(**{"Transaction ID": "TX-B", "Payment ID": "PAY-B",
                               "Net Sales": "£5.00", "Gross Sales": "£5.00",
                               "Source": "Point of Sale",
                               "Dining Option": "Pick Up, Takeaway"}),
        ],
        items=[
            item_row(**{"Transaction ID": "TX-A", "Product Sales": "£5.00"}),
            item_row(**{"Transaction ID": "TX-B", "Product Sales": "£5.00"}),
        ],
    )

    outcome = SquareImportService(session_factory).run(request)

    assert outcome.orders_created == 2
    with session_factory() as s:
        channels = {
            o.source_order_id: o.channel for o in s.scalars(select(Order)).all()
        }
    assert channels["TX-A"] is Channel.MIXED
    assert channels["TX-B"] is Channel.MIXED


def test_importer_persists_line_level_discounts(session_factory, square_files):
    """The source value reaches the database unchanged, per line."""
    request = square_files(
        transactions=[
            transaction_row(**{"Transaction ID": "TX-D", "Payment ID": "PAY-D",
                               "Gross Sales": "£7.50", "Discounts": "-£2.50",
                               "Net Sales": "£7.50"})
        ],
        items=[
            item_row(**{"Transaction ID": "TX-D", "Item": "Discounted",
                        "Product Sales": "£5.00", "Discounts": "-£2.50"}),
            item_row(**{"Transaction ID": "TX-D", "Item": "Full Price",
                        "Product Sales": "£5.00", "Discounts": "£0.00"}),
        ],
    )
    SquareImportService(session_factory).run(request)

    with session_factory() as s:
        rows = {
            item.product.name: item
            for item in s.scalars(select(OrderItem)).all()
        }
        assert rows["Discounted"].discount_amount == 250
        assert rows["Full Price"].discount_amount == 0
        # The whole order's discount is accounted for, without apportionment.
        assert sum(r.discount_amount for r in rows.values()) == 250


def test_line_discount_difference_is_a_conflicting_order(
    session_factory, square_files
):
    """Two exports agreeing on totals but disagreeing on which line was
    discounted is a genuine conflict, not a safe duplicate."""
    service = SquareImportService(session_factory)
    base_tx = transaction_row(**{"Transaction ID": "TX-D", "Payment ID": "PAY-D",
                                 "Gross Sales": "£7.50", "Discounts": "-£2.50",
                                 "Net Sales": "£7.50"})
    service.run(square_files(
        transactions=[base_tx],
        items=[
            item_row(**{"Transaction ID": "TX-D", "Item": "A",
                        "Product Sales": "£5.00", "Discounts": "-£2.50"}),
            item_row(**{"Transaction ID": "TX-D", "Item": "B",
                        "Product Sales": "£5.00", "Discounts": "£0.00"}),
        ],
        label="first",
    ))

    with pytest.raises(ConflictingOrderError, match="line_items"):
        service.run(square_files(
            transactions=[{**base_tx, "Customer Name": "re-export"}],
            items=[
                item_row(**{"Transaction ID": "TX-D", "Item": "A",
                            "Product Sales": "£5.00", "Discounts": "£0.00"}),
                item_row(**{"Transaction ID": "TX-D", "Item": "B",
                            "Product Sales": "£5.00", "Discounts": "-£2.50"}),
            ],
            label="second",
        ))


# --- zero-value orders that served something ---------------------------------
#
# Square records a no-sale and a real order served for nothing identically at
# the transaction level: £0.00 gross, net and discount. Only the items file
# distinguishes them. Dropping both lost the served unit from unit counts,
# product analytics and basket co-occurrence, and surfaced much later as a
# one-unit reconciliation mismatch — exactly what happened to July 2026.


def zero_value_import(square_files, items, label="z", tx_id="TX-Z", **tx_overrides):
    """A £0.00 payment, with whatever item lines the caller supplies."""
    tx = {"Transaction ID": tx_id, "Payment ID": f"PAY-{tx_id}",
          "Gross Sales": "£0.00", "Net Sales": "£0.00", "Discounts": "£0.00",
          "Total Collected": "£0.00"}
    tx.update(tx_overrides)
    return square_files(transactions=[transaction_row(**tx)], items=items, label=label)


def test_zero_value_no_sale_with_no_items_is_still_skipped(
    session_factory, square_files
):
    """The deliberate exclusion, unchanged. 446 of the 447 zero-value rows in
    the real trading year are exactly this."""
    request = square_files(
        transactions=[
            transaction_row(**{"Transaction ID": "TX-OK", "Payment ID": "PAY-OK",
                               "Gross Sales": "£3.65", "Net Sales": "£3.65"}),
            transaction_row(**{"Transaction ID": "TX-NOSALE", "Payment ID": "PAY-NS",
                               "Gross Sales": "£0.00", "Net Sales": "£0.00"}),
        ],
        items=[item_row(**{"Transaction ID": "TX-OK", "Product Sales": "£3.65"})],
    )

    outcome = SquareImportService(session_factory).run(request)

    assert outcome.orders_created == 1
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(Order)) == 1
        assert s.scalar(select(Order.source_order_id)) == "TX-OK"
        batch = s.get(ImportBatch, outcome.batch_id)
        assert "zero_value_transaction" in batch.error_log


def test_zero_value_payment_with_a_real_item_is_retained(
    session_factory, square_files
):
    """A glass of tap water is a sale. It cost nothing; it still happened."""
    request = zero_value_import(
        square_files,
        items=[item_row(**{"Transaction ID": "TX-Z", "Item": "Tap Water",
                           "Price Point Name": "Regular", "Qty": "1.0",
                           "Product Sales": "£0.00", "Net Sales": "£0.00"})],
    )

    outcome = SquareImportService(session_factory).run(request)

    assert outcome.orders_created == 1
    with session_factory() as s:
        order = s.scalar(select(Order))
        assert order.source_order_id == "TX-Z"
        assert order.event_type is OrderEventType.PAYMENT
        assert order.net_amount == 0
        assert order.gross_amount == 0
        # The unit is the whole point.
        assert order.item_count == 1
        assert s.scalar(select(func.count()).select_from(OrderItem)) == 1
        assert s.scalar(select(Product.name)) == "Tap Water"


def test_retained_zero_value_order_is_reported_not_silent(
    session_factory, square_files
):
    """Retention is a decision about the data and is recorded as one."""
    outcome = SquareImportService(session_factory).run(
        zero_value_import(
            square_files,
            items=[item_row(**{"Transaction ID": "TX-Z", "Item": "Tap Water",
                               "Product Sales": "£0.00"})],
        )
    )
    with session_factory() as s:
        batch = s.get(ImportBatch, outcome.batch_id)
        assert "zero_value_order_retained" in batch.error_log
        # It is no longer counted as a skipped row: it became an order.
        tx_file = s.scalar(
            select(ImportFile).where(ImportFile.role == ImportFileRole.TRANSACTIONS)
        )
        assert tx_file.rows_skipped == 0
        assert tx_file.rows_imported == 1


def test_multiple_zero_priced_items_are_all_retained(session_factory, square_files):
    request = zero_value_import(
        square_files,
        items=[
            item_row(**{"Transaction ID": "TX-Z", "Item": "Tap Water",
                        "Price Point Name": "Regular", "Qty": "2.0",
                        "Product Sales": "£0.00"}),
            item_row(**{"Transaction ID": "TX-Z", "Item": "Birthday Candle",
                        "Price Point Name": "", "Qty": "1.0",
                        "Product Sales": "£0.00"}),
        ],
    )

    outcome = SquareImportService(session_factory).run(request)

    assert outcome.orders_created == 1
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(OrderItem)) == 2
        assert s.scalar(select(Order.item_count)) == 3      # 2 + 1
        assert s.scalar(select(func.sum(OrderItem.line_total))) == 0


def test_retained_zero_value_order_contributes_no_money_but_real_counts(
    session_factory, square_files
):
    """£0 of revenue, one more paid order, and the units it served."""
    request = square_files(
        transactions=[
            transaction_row(**{"Transaction ID": "TX-PAID", "Payment ID": "PAY-P",
                               "Gross Sales": "£10.00", "Net Sales": "£10.00"}),
            transaction_row(**{"Transaction ID": "TX-Z", "Payment ID": "PAY-Z",
                               "Gross Sales": "£0.00", "Net Sales": "£0.00"}),
        ],
        items=[
            item_row(**{"Transaction ID": "TX-PAID", "Item": "Caffe Latte",
                        "Qty": "1.0", "Product Sales": "£10.00"}),
            item_row(**{"Transaction ID": "TX-Z", "Item": "Tap Water",
                        "Qty": "1.0", "Product Sales": "£0.00"}),
        ],
    )

    SquareImportService(session_factory).run(request)

    with session_factory() as s:
        assert s.scalar(select(func.sum(Order.net_amount))) == 1000     # unchanged
        assert s.scalar(
            select(func.count()).select_from(Order).where(
                Order.event_type == OrderEventType.PAYMENT
            )
        ) == 2                                                          # both count
        assert s.scalar(select(func.sum(Order.item_count))) == 2        # both units


def test_zero_priced_product_is_visible_to_product_analytics(
    session_factory, square_files
):
    """It must reach the product tables, or the menu is misrepresented."""
    SquareImportService(session_factory).run(
        zero_value_import(
            square_files,
            items=[item_row(**{"Transaction ID": "TX-Z", "Item": "Tap Water",
                               "Price Point Name": "Regular", "Qty": "1.0",
                               "Product Sales": "£0.00",
                               "Category": "Cold Drinks Menu"})],
        )
    )

    ranking = AnalyticsService(session_factory).products(
        date(2026, 8, 1), date(2026, 8, 31)
    )
    rows = {(s.totals.name, s.totals.variation): s.totals for s in ranking.products}

    assert ("Tap Water", "Regular") in rows
    totals = rows[("Tap Water", "Regular")]
    assert totals.net_units == 1
    assert totals.net_sales_pence == 0
    assert totals.payment_order_count == 1


def test_zero_priced_item_participates_in_basket_pairs(session_factory, square_files):
    """Tap Water co-occurs constantly in the real data; excluding it would
    misstate what is bought together."""
    request = zero_value_import(
        square_files,
        items=[
            item_row(**{"Transaction ID": "TX-Z", "Item": "Tap Water",
                        "Price Point Name": "Regular", "Qty": "1.0",
                        "Product Sales": "£0.00"}),
            item_row(**{"Transaction ID": "TX-Z", "Item": "Poached Egg",
                        "Price Point Name": "", "Qty": "1.0",
                        "Product Sales": "£0.00"}),
        ],
    )
    SquareImportService(session_factory).run(request)

    analysis = AnalyticsService(session_factory).product_pairs(
        date(2026, 8, 1), date(2026, 8, 31)
    )
    names = {
        frozenset({p.counts.a.name, p.counts.b.name}) for p in analysis.pairs
    }
    assert frozenset({"Tap Water", "Poached Egg"}) in names


def test_refunds_are_unaffected_by_the_zero_value_change(
    session_factory, square_files
):
    """A refund never took the zero-value path and still does not."""
    request = square_files(
        transactions=[
            transaction_row(**{"Transaction ID": "TX-P", "Payment ID": "PAY-1",
                               "Gross Sales": "£10.00", "Net Sales": "£10.00"}),
            transaction_row(**{"Transaction ID": "TX-R", "Payment ID": "PAY-1",
                               "Event Type": "Refund", "Gross Sales": "-£10.00",
                               "Net Sales": "-£10.00"}),
        ],
        items=[item_row(**{"Transaction ID": "TX-P", "Product Sales": "£10.00"})],
    )

    SquareImportService(session_factory).run(request)

    with session_factory() as s:
        orders = {o.source_order_id: o for o in s.scalars(select(Order)).all()}
        assert orders["TX-R"].event_type is OrderEventType.REFUND
        assert s.scalar(select(func.sum(Order.net_amount))) == 0


def test_ordinary_positive_orders_are_untouched(session_factory, square_files):
    """The common path must not have moved."""
    outcome = SquareImportService(session_factory).run(simple_import(square_files))

    assert outcome.orders_created == 1
    with session_factory() as s:
        assert s.scalar(select(Order.net_amount)) == 1095
        assert s.scalar(select(func.count()).select_from(OrderItem)) == 2
        batch = s.get(ImportBatch, outcome.batch_id)
        assert "zero_value_order_retained" not in (batch.error_log or "")


def test_zero_value_order_with_items_but_no_channel_is_rejected(
    session_factory, square_files
):
    """A real order we cannot classify fails loudly rather than vanishing.

    Composes with the unresolved-channel hotfix: promotion happens first, so
    an unclassifiable £0 order is caught like any other unclassifiable order.
    """
    request = zero_value_import(
        square_files,
        items=[item_row(**{"Transaction ID": "TX-Z", "Item": "Tap Water",
                           "Product Sales": "£0.00"})],
        **{"Source": "Mystery Co"},
    )

    with pytest.raises(UnresolvedChannelError) as caught:
        SquareImportService(session_factory).run(request)

    assert "TX-Z" in str(caught.value)
    assert counts(session_factory)["orders"] == 0
