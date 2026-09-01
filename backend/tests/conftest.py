"""Shared fixtures.

Every fixture here is SYNTHETIC. The real café exports are gitignored and are
never referenced by the test suite — tests must pass on a fresh clone with no
access to any real business data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DELIMITER = "\t"

TRANSACTION_COLUMNS = [
    "Date", "Time", "Time Zone", "Gross Sales", "Discounts", "Service Charges",
    "Net Sales", "Tax", "Tip", "Total Collected", "Source", "Transaction ID",
    "Payment ID", "Event Type", "Dining Option", "Channel", "Refund Reason",
    # Columns the adapter must never bind:
    "Customer ID", "Customer Name", "Card Brand", "PAN Suffix", "Staff Name",
]

ITEM_COLUMNS = [
    "Date", "Time", "Time Zone", "Category", "Item", "Qty", "Price Point Name",
    "SKU", "Modifiers Applied", "Product Sales", "Discounts", "Net Sales",
    "Gross Sales", "Transaction ID", "Event Type", "Itemisation Type",
    "Customer Name", "Employee",
]

SUMMARY_COLUMNS = [
    "Item Name", "Item Variation", "SKU", "Category", "Items Sold",
    "Product Sales", "Items Refunded", "Refunds", "Discounts & Comps",
    "Net Sales", "Tax", "Gross Sales", "Units Sold",
]


def write_square_export(
    path: Path,
    columns: list[str],
    rows: list[dict[str, str]],
    *,
    encoding: str = "utf-16",
    delimiter: str = DELIMITER,
) -> Path:
    """Write a file in Square's actual export format: UTF-16, tab-delimited.

    `encoding` and `delimiter` are parameters so tests can produce deliberately
    malformed files and assert the adapter rejects them.
    """
    lines = [delimiter.join(columns)]
    lines.extend(delimiter.join(row.get(col, "") for col in columns) for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding=encoding)
    return path


def transaction_row(**overrides: str) -> dict[str, str]:
    row = {
        "Date": "2026-08-15", "Time": "12:30:00", "Time Zone": "London",
        "Gross Sales": "£10.00", "Discounts": "£0.00", "Service Charges": "£0.00",
        "Net Sales": "£10.00", "Tax": "£0.00", "Tip": "£0.00",
        "Total Collected": "£10.00", "Source": "Register",
        "Transaction ID": "TX-1", "Payment ID": "PAY-1", "Event Type": "Payment",
        "Dining Option": "Eat in", "Channel": "The Coffee Lounge",
        "Customer Name": "A Person", "Customer ID": "CUST-9",
        "Card Brand": "Visa", "PAN Suffix": "4242", "Staff Name": "A Barista",
    }
    row.update(overrides)
    return row


def item_row(**overrides: str) -> dict[str, str]:
    row = {
        "Date": "2026-08-15", "Time": "12:30:00", "Time Zone": "London",
        "Category": "Speciality Coffee", "Item": "Caffe Latte", "Qty": "1.0",
        "Price Point Name": "Regular", "Modifiers Applied": "Whole Milk",
        "Product Sales": "£3.65", "Discounts": "£0.00", "Net Sales": "£3.65",
        "Gross Sales": "£3.65", "Transaction ID": "TX-1", "Event Type": "Payment",
        "Itemisation Type": "Prepared Food and Beverage",
        "Customer Name": "A Person", "Employee": "A Barista",
    }
    row.update(overrides)
    return row


@pytest.fixture
def transactions_file(tmp_path: Path):
    def _make(rows: list[dict[str, str]], **kwargs) -> Path:
        return write_square_export(
            tmp_path / "transactions.csv", TRANSACTION_COLUMNS, rows, **kwargs
        )

    return _make


@pytest.fixture
def items_file(tmp_path: Path):
    def _make(rows: list[dict[str, str]], **kwargs) -> Path:
        return write_square_export(tmp_path / "items.csv", ITEM_COLUMNS, rows, **kwargs)

    return _make


@pytest.fixture
def summary_file(tmp_path: Path):
    def _make(rows: list[dict[str, str]], **kwargs) -> Path:
        return write_square_export(
            tmp_path / "summary.csv", SUMMARY_COLUMNS, rows, **kwargs
        )

    return _make


# --- database fixtures -------------------------------------------------------
#
# These run against the real PostgreSQL service from docker-compose. Testing
# persistence against SQLite would not exercise the constraints that matter:
# ON DELETE RESTRICT, composite unique constraints and NULL-distinctness all
# behave differently there, and those are precisely what we rely on.

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.db import engine


@pytest.fixture(scope="session")
def database():
    """Build the schema by running the MIGRATIONS, not metadata.create_all().

    create_all() would build the schema the models describe, which is not
    necessarily the schema a deployment actually gets. Running alembic here
    means the tests exercise exactly what `alembic upgrade head` produces, so a
    migration that drifts from the models fails the suite rather than passing
    against a schema that only exists in tests.
    """
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config("alembic.ini"), "head")
    yield engine


@pytest.fixture
def session_factory(database):
    """A clean set of sales tables for every test."""
    with database.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE order_items, orders, products, import_files, "
                "import_batches RESTART IDENTITY CASCADE"
            )
        )
    return sessionmaker(bind=database, autoflush=False, expire_on_commit=False)


@pytest.fixture
def square_files(tmp_path):
    """Build a complete, self-consistent set of Square export files."""

    def _make(transactions, items, summary=None, label="test-batch"):
        from app.services.importer import ImportRequest

        tx = write_square_export(
            tmp_path / f"transactions-{label}.csv", TRANSACTION_COLUMNS, transactions
        )
        it = write_square_export(tmp_path / f"items-{label}.csv", ITEM_COLUMNS, items)
        sm = (
            write_square_export(
                tmp_path / f"summary-{label}.csv", SUMMARY_COLUMNS, summary
            )
            if summary is not None
            else None
        )
        return ImportRequest(transactions=tx, items=it, summary=sm, label=label)

    return _make


def summary_row(**overrides):
    row = {
        "Item Name": "Caffe Latte", "Item Variation": "Regular", "SKU": "",
        "Category": "Speciality Coffee", "Items Sold": "1",
        "Product Sales": "£3.65", "Items Refunded": "0", "Refunds": "£0.00",
        "Discounts & Comps": "£0.00", "Net Sales": "£3.65", "Tax": "£0.00",
        "Gross Sales": "£3.65", "Units Sold": "1",
    }
    row.update(overrides)
    return row
