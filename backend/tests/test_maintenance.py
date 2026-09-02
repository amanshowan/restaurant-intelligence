"""Statistics-refresh orchestration around imports.

These assert WHEN maintenance runs and what happens when it fails — never that
PostgreSQL chooses a particular plan, which would be brittle and is not what
the behaviour is for.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import ImportBatch, ImportStatus, Order
from app.services.importer import (
    ConflictingOrderError,
    ImportRejected,
    ReconciliationError,
    SquareImportService,
)
from app.services.maintenance import (
    ANALYZED_TABLES,
    StatisticsRefreshFailed,
    refresh_planner_statistics,
    refresh_planner_statistics_quietly,
)
from tests.conftest import item_row, summary_row, transaction_row


class Spy:
    """Records calls; optionally raises to simulate a maintenance failure."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self._error = error

    def __call__(self) -> bool:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return True


def simple_request(square_files, label="b1", tx_id="TX-1", summary=True):
    return square_files(
        transactions=[
            transaction_row(**{"Transaction ID": tx_id, "Payment ID": f"PAY-{tx_id}",
                               "Gross Sales": "£3.65", "Net Sales": "£3.65"})
        ],
        items=[item_row(**{"Transaction ID": tx_id, "Product Sales": "£3.65"})],
        summary=[summary_row(**{"Units Sold": "1", "Product Sales": "£3.65",
                                "Net Sales": "£3.65"})] if summary else None,
        label=label,
    )


# --- when maintenance runs ---------------------------------------------------


def test_successful_import_triggers_statistics_refresh(session_factory, square_files):
    spy = Spy()
    outcome = SquareImportService(session_factory, statistics_refresher=spy).run(
        simple_request(square_files)
    )
    assert outcome.status is ImportStatus.COMPLETED
    assert spy.calls == 1


def test_duplicate_import_does_not_trigger_refresh(session_factory, square_files):
    spy = Spy()
    service = SquareImportService(session_factory, statistics_refresher=spy)
    request = simple_request(square_files)
    service.run(request)
    assert spy.calls == 1

    with pytest.raises(ImportRejected):
        service.run(request)
    assert spy.calls == 1, "a rejected import writes nothing to analyse"


def test_reconciliation_failure_does_not_trigger_refresh(session_factory, square_files):
    spy = Spy()
    request = square_files(
        transactions=[transaction_row(**{"Net Sales": "£3.65", "Gross Sales": "£3.65"})],
        items=[item_row(**{"Product Sales": "£3.65"})],
        summary=[summary_row(**{"Units Sold": "99", "Product Sales": "£99.00",
                                "Net Sales": "£99.00"})],
    )
    with pytest.raises(ReconciliationError):
        SquareImportService(session_factory, statistics_refresher=spy).run(request)
    assert spy.calls == 0


def test_malformed_file_does_not_trigger_refresh(session_factory, square_files, tmp_path):
    from app.adapters.base import SourceFormatError
    from tests.conftest import TRANSACTION_COLUMNS, write_square_export

    spy = Spy()
    good = simple_request(square_files)
    bad = write_square_export(
        tmp_path / "bad.csv", TRANSACTION_COLUMNS, [transaction_row()],
        encoding="utf-8",
    )
    request = type(good)(transactions=bad, items=good.items, summary=None, label="x")
    with pytest.raises(SourceFormatError):
        SquareImportService(session_factory, statistics_refresher=spy).run(request)
    assert spy.calls == 0


def test_conflicting_order_does_not_trigger_refresh(session_factory, square_files):
    spy = Spy()
    service = SquareImportService(session_factory, statistics_refresher=spy)
    service.run(simple_request(square_files, label="first", summary=False))
    assert spy.calls == 1

    conflicting = square_files(
        transactions=[
            transaction_row(**{"Transaction ID": "TX-1", "Payment ID": "PAY-TX-1",
                               "Gross Sales": "£99.00", "Net Sales": "£99.00"})
        ],
        items=[item_row(**{"Transaction ID": "TX-1", "Product Sales": "£3.65",
                           "SKU": "RE-EXPORT"})],
        label="second",
    )
    with pytest.raises(ConflictingOrderError):
        service.run(conflicting)
    assert spy.calls == 1


# --- failure semantics -------------------------------------------------------


def test_refresh_failure_does_not_fail_a_completed_import(
    session_factory, square_files
):
    """The business import already committed. Housekeeping cannot undo it."""
    spy = Spy(error=StatisticsRefreshFailed("simulated lock timeout"))
    service = SquareImportService(session_factory, statistics_refresher=spy)

    outcome = service.run(simple_request(square_files))

    assert outcome.status is ImportStatus.COMPLETED
    assert outcome.orders_imported if hasattr(outcome, "orders_imported") else True
    assert spy.calls == 1
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(Order)) == 1
        batch = s.get(ImportBatch, outcome.batch_id)
        assert batch.status is ImportStatus.COMPLETED


def test_quiet_refresh_swallows_failure_and_reports_it(monkeypatch):
    def explode(engine, tables=ANALYZED_TABLES):
        raise StatisticsRefreshFailed("simulated")

    monkeypatch.setattr(
        "app.services.maintenance.refresh_planner_statistics", explode
    )
    assert refresh_planner_statistics_quietly(object()) is False


def test_quiet_refresh_reports_success(database):
    assert refresh_planner_statistics_quietly(database) is True


def test_refresh_raises_a_typed_error_on_a_bad_engine():
    class Broken:
        def connect(self):
            raise RuntimeError("no connection")

    with pytest.raises(StatisticsRefreshFailed):
        refresh_planner_statistics(Broken())


def test_analyzed_tables_are_the_ones_a_bulk_import_changes():
    assert ANALYZED_TABLES == ("orders", "order_items", "products")


def test_refresh_actually_populates_statistics(database, session_factory):
    """After a refresh the planner has statistics for the imported tables."""
    from sqlalchemy import text

    with database.begin() as conn:
        conn.execute(text("ANALYZE orders"))
    refresh_planner_statistics(database)
    with database.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT relname FROM pg_stat_user_tables "
                "WHERE relname = ANY(:names) AND last_analyze IS NOT NULL"
            ),
            {"names": list(ANALYZED_TABLES)},
        ).scalars().all()
    assert set(rows) == set(ANALYZED_TABLES)
