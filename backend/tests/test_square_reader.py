"""File-format detection: encoding, delimiter and schema must be asserted."""

from __future__ import annotations

import pytest

from app.adapters.base import SourceFormatError, SourceSchemaError
from app.adapters.square import SquareAdapter, detect_encoding, read_rows
from app.models.enums import ImportFileRole
from tests.conftest import (
    ITEM_COLUMNS,
    SUMMARY_COLUMNS,
    TRANSACTION_COLUMNS,
    item_row,
    transaction_row,
    write_square_export,
)


def test_reads_utf16_tab_delimited_export(transactions_file):
    path = transactions_file([transaction_row()])
    assert detect_encoding(path) == "utf-16"
    rows, fieldnames = read_rows(path, ImportFileRole.TRANSACTIONS)
    assert len(rows) == 1
    assert "Transaction ID" in fieldnames


def test_utf8_file_is_rejected_with_an_actionable_message(transactions_file):
    """The most likely real failure: someone re-saved the export in Excel."""
    path = transactions_file([transaction_row()], encoding="utf-8")
    with pytest.raises(SourceFormatError, match="UTF-16"):
        detect_encoding(path)


def test_utf8_bom_names_the_likely_cause(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text("Date\tTime\n", encoding="utf-8-sig")
    with pytest.raises(SourceFormatError, match="re-saved by a spreadsheet"):
        detect_encoding(path)


def test_comma_delimited_utf16_file_is_rejected(transactions_file):
    """UTF-16 alone is not enough — the delimiter is asserted separately."""
    path = transactions_file([transaction_row()], delimiter=",")
    with pytest.raises(SourceFormatError, match="tab-delimited"):
        read_rows(path, ImportFileRole.TRANSACTIONS)


def test_missing_required_columns_are_named(tmp_path):
    path = write_square_export(
        tmp_path / "t.csv", ["Date", "Time", "Time Zone"], [{"Date": "2026-08-15"}]
    )
    with pytest.raises(SourceSchemaError) as exc:
        read_rows(path, ImportFileRole.TRANSACTIONS)
    message = str(exc.value)
    assert "Transaction ID" in message and "Net Sales" in message


def test_wrong_role_for_a_valid_file_is_rejected(items_file):
    """An Items export read as Transactions fails loudly, not silently."""
    path = items_file([item_row()])
    with pytest.raises(SourceSchemaError, match="transactions"):
        read_rows(path, ImportFileRole.TRANSACTIONS)


def test_empty_file_with_valid_header_yields_no_rows(transactions_file):
    path = transactions_file([])
    result = SquareAdapter().read(path, ImportFileRole.TRANSACTIONS)
    assert result.rows_read == 0
    assert result.orders == []
