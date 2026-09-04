"""Shared fixtures.

Every fixture here is SYNTHETIC. The real café exports are gitignored and are
never referenced by the test suite — tests must pass on a fresh clone with no
access to any real business data.

The first thing this module does, before anything else, is point the whole
process at a DEDICATED TEST DATABASE. See the block below.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest

# =============================================================================
# Test database isolation
# =============================================================================
#
# This block MUST run before anything imports `app.config` or `app.db`.
# `Settings` is instantiated at import time and `app.db` builds its engine from
# it at import time, so by the time either module has been imported the choice
# of database is already made and cannot be taken back.
#
# conftest.py is the first module pytest imports, which is what makes this the
# one reliable place to make that choice.
#
# WHY THIS EXISTS
# ---------------
# The suite is destructive by design: `session_factory` TRUNCATEs every sales
# table before each test, and tests/test_migrations.py downgrades the schema to
# base and back. Previously all of that ran against whatever `DATABASE_URL`
# pointed at — which, inside the Compose stack, is the development database
# holding imported Square data. Running the tests silently destroyed it.
#
# HOW
# ---
# Rather than teach every fixture and helper to carry a second URL around, the
# process-wide `DATABASE_URL` is REPLACED with the test URL here. Everything
# downstream — `app.db.engine`, `SessionLocal`, Alembic's env.py, and the
# service classes — then resolves to the test database with no knowledge that
# anything unusual happened, and no test can reach the development database
# even by accident.
#
# Application code is untouched: outside pytest, `DATABASE_URL` means exactly
# what it has always meant.

#: Where the test database URL must come from. Deliberately a DIFFERENT
#: variable to DATABASE_URL, so that pointing the suite somewhere is always a
#: deliberate act rather than an inherited default.
TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"

#: A test database must be named so that it cannot be mistaken for anything
#: else. This is the whole guard: a suffix a production or development database
#: would never plausibly carry.
TEST_DATABASE_SUFFIX = "_test"

#: Where the ORIGINAL DATABASE_URL is stashed before it is redirected below.
#:
#: This module's body runs TWICE: once when pytest imports it as `conftest`,
#: and again as `tests.conftest` when a test module imports a shared helper
#: from it (five of them do). By the second run DATABASE_URL already holds the
#: test URL, so a naive "are these two the same?" check would compare the test
#: URL against itself and refuse to run. Stashing the original the first time
#: through makes the comparison meaningful and the whole block idempotent.
DEVELOPMENT_DATABASE_URL_ENV = "RI_DEVELOPMENT_DATABASE_URL"


class UnsafeTestDatabase(RuntimeError):
    """The suite refuses to run against the configured database.

    Raised at import time, so it aborts collection before a single destructive
    fixture has had the chance to execute. Failing loudly here is the entire
    point: the alternative — quietly falling back to DATABASE_URL — is the
    defect this module exists to prevent.
    """


def database_name(url: str) -> str:
    """The database name from a SQLAlchemy URL, without connecting."""
    return urlsplit(url).path.lstrip("/")


def assert_is_test_database(url: str) -> str:
    """Return `url`, or raise if it does not name an obvious test database.

    Checked on the NAME rather than the host or port, because the dangerous
    case is precisely the one where everything else is identical: the test and
    development databases live on the same PostgreSQL server, with the same
    credentials, and differ only here.
    """
    name = database_name(url)

    if not name:
        raise UnsafeTestDatabase(
            f"{TEST_DATABASE_URL_ENV} names no database: {url!r}"
        )

    if not name.endswith(TEST_DATABASE_SUFFIX):
        raise UnsafeTestDatabase(
            f"refusing to run destructive tests against database {name!r}: "
            f"the test database name must end with {TEST_DATABASE_SUFFIX!r}.\n"
            f"This suite TRUNCATEs every sales table and downgrades the schema "
            f"to base. Point {TEST_DATABASE_URL_ENV} at a dedicated database "
            f"(for example {name}{TEST_DATABASE_SUFFIX})."
        )

    return url


def _resolve_test_database_url() -> str:
    """The test database URL, or a refusal to run.

    There is deliberately NO fallback to DATABASE_URL. An unset variable is a
    misconfiguration, and inheriting the development database is exactly the
    outcome being prevented.
    """
    url = os.environ.get(TEST_DATABASE_URL_ENV)

    if not url:
        raise UnsafeTestDatabase(
            f"{TEST_DATABASE_URL_ENV} is not set, and this suite will not fall "
            f"back to DATABASE_URL — it would destroy the data in it.\n"
            f"Inside the Compose stack the variable is already set on the api "
            f"service; run the suite with:\n"
            f"    docker compose exec api python -m pytest"
        )

    # setdefault, so the first execution records the real development URL and
    # every later one reads it back rather than seeing the redirected value.
    # Correct whichever import happens first.
    development_url = os.environ.setdefault(
        DEVELOPMENT_DATABASE_URL_ENV, os.environ.get("DATABASE_URL", "")
    )
    if development_url and url == development_url:
        # Belt and braces. The suffix check above would normally have caught
        # this, but an identical URL is worth naming precisely, because it is
        # the specific mistake with the worst consequence.
        raise UnsafeTestDatabase(
            f"{TEST_DATABASE_URL_ENV} is identical to DATABASE_URL "
            f"({database_name(url)!r}). The test database must be a separate "
            f"database, not the one the application and dashboard use."
        )

    return assert_is_test_database(url)


def _ensure_test_database_exists(url: str) -> None:
    """Create the test database if it does not exist yet.

    Done here rather than in a Postgres init script because those run only when
    the data volume is first initialised. Anyone with an existing volume — that
    is, anyone who has used this project before today — would otherwise have to
    create the database by hand, and a setup step that is easy to skip is a
    setup step that gets skipped.

    Connects to the `postgres` maintenance database on the same server, using
    the credentials from the test URL itself.
    """
    from sqlalchemy import create_engine, text

    # Normalised here as well as in Settings: this engine is built from the
    # raw TEST_DATABASE_URL, before app.config has been imported, so it does
    # not benefit from the field validator. A generic scheme would fail on
    # psycopg2 while the application itself worked.
    from app.db_url import normalise_database_url

    name = database_name(url)
    maintenance_url = normalise_database_url(url.rsplit("/", 1)[0] + "/postgres")

    # CREATE DATABASE cannot run inside a transaction block, hence AUTOCOMMIT.
    engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": name},
            ).scalar()
            if not exists:
                # PostgreSQL has no CREATE DATABASE IF NOT EXISTS, and the name
                # cannot be a bind parameter. It comes from our own validated
                # environment, and the suffix check has already constrained it.
                conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        engine.dispose()


TEST_DATABASE_URL = _resolve_test_database_url()
_ensure_test_database_exists(TEST_DATABASE_URL)

# The redirection itself. Everything imported from `app.*` below this line —
# and in every test module — now resolves to the test database. Assigning the
# same value again on this module's second execution is a no-op.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

# =============================================================================

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

    Alembic reads its URL from `settings.database_url`, which the block at the
    top of this module has already pointed at the test database — so the
    migration-based setup is preserved exactly, it simply runs somewhere safe.
    """
    from alembic import command
    from alembic.config import Config

    # The second checkpoint, and the one that guards the engine ACTUALLY in
    # use rather than the environment it was built from. Every destructive
    # fixture in the suite depends on this one, so nothing truncates a table or
    # downgrades a schema without passing through here first.
    assert_is_test_database(engine.url.render_as_string(hide_password=False))

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


# --- analytics fixtures ------------------------------------------------------


@pytest.fixture
def make_order(session_factory):
    """Insert an order directly, dated in LOCAL (Europe/London) wall time.

    Bypasses the importer deliberately: these tests are about aggregation and
    timezone handling, and building fixtures from local wall time is how the
    boundary cases are actually expressed.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.models import Order
    from app.models.enums import Channel, OrderEventType

    LONDON = ZoneInfo("Europe/London")
    counter = {"n": 0}

    def _make(
        local: str,
        net: int,
        *,
        gross: int | None = None,
        discount: int = 0,
        units: int = 1,
        event_type: OrderEventType = OrderEventType.PAYMENT,
        channel: Channel = Channel.IN_STORE,
    ):
        counter["n"] += 1
        occurred = datetime.fromisoformat(local).replace(tzinfo=LONDON)
        with session_factory() as s:
            s.add(
                Order(
                    source="square",
                    source_order_id=f"TX-{counter['n']:04d}",
                    occurred_at=occurred,
                    channel=channel,
                    event_type=event_type,
                    gross_amount=net + discount if gross is None else gross,
                    discount_amount=discount,
                    net_amount=net,
                    item_count=units,
                )
            )
            s.commit()

    return _make


@pytest.fixture
def make_sale(session_factory):
    """Insert an order with product lines, dated in LOCAL wall time.

    `lines` is a list of (name, variation, quantity, line_total_pence[, kind
    [, line_discount_pence]]). Products are created on demand and reused by
    (name, variation).

    `discount` is the ORDER total; when line discounts are not given explicitly
    it is placed entirely on the first line, so the two stay consistent.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    from app.models import Order, OrderItem, Product
    from app.models.enums import Channel, OrderEventType, ProductKind

    LONDON = ZoneInfo("Europe/London")
    counter = {"n": 0}

    def _make(
        local: str,
        lines,
        *,
        discount: int = 0,
        event_type: OrderEventType = OrderEventType.PAYMENT,
        channel: Channel = Channel.IN_STORE,
    ):
        counter["n"] += 1
        occurred = datetime.fromisoformat(local).replace(tzinfo=LONDON)
        with session_factory() as s:
            gross = sum(line[3] for line in lines)
            order = Order(
                source="square",
                source_order_id=f"SALE-{counter['n']:04d}",
                occurred_at=occurred,
                channel=channel,
                event_type=event_type,
                gross_amount=gross,
                discount_amount=discount,
                net_amount=gross - discount,
                item_count=sum(line[2] for line in lines),
            )
            s.add(order)
            s.flush()
            for index, (name, variation, qty, total, *rest) in enumerate(lines):
                kind = rest[0] if rest else ProductKind.MENU_ITEM
                if len(rest) > 1:
                    line_discount = rest[1]
                else:
                    line_discount = discount if index == 0 else 0
                product = s.scalar(
                    select(Product).where(
                        Product.name == name, Product.variation == variation
                    )
                )
                if product is None:
                    product = Product(name=name, variation=variation, kind=kind)
                    s.add(product)
                    s.flush()
                s.add(
                    OrderItem(
                        order_id=order.id,
                        product_id=product.id,
                        quantity=qty,
                        unit_price=abs(total) // max(abs(qty), 1),
                        line_total=total,
                        discount_amount=line_discount,
                    )
                )
            s.commit()
            return order.id

    return _make


@pytest.fixture
def product_id(session_factory):
    """Look up a product id by (name, variation)."""
    from sqlalchemy import select

    from app.models import Product

    def _lookup(name: str, variation: str = "") -> int:
        with session_factory() as s:
            return s.scalar(
                select(Product.id).where(
                    Product.name == name, Product.variation == variation
                )
            )

    return _lookup


# --- natural-language layer fixtures (M7 Commit 25) --------------------------
#
# The deterministic suite NEVER makes a provider call. Every test below runs
# against `FakeLLM`, which satisfies the `LLMClient` protocol, returns whatever
# the test queues, and records exactly what it was asked — which is what makes
# prompt content, grounding inputs and injection handling assertable.


class FakeLLM:
    """A scripted `LLMClient`.

    Queue responses (or exceptions) per stage; they are returned in order. Every
    call is recorded, so a test can assert what the model was actually shown —
    the only reliable way to test that untrusted text stayed in the user
    message and that the answer stage received nothing but evidence.
    """

    def __init__(
        self,
        *,
        structured: list | None = None,
        text: list | None = None,
        model: str = "fake-model-1",
    ) -> None:
        self._structured = list(structured or [])
        self._text = list(text or [])
        self._model = model
        self.structured_calls: list[dict] = []
        self.text_calls: list[dict] = []

    @property
    def model(self) -> str:
        return self._model

    def complete_structured(self, *, system, user, schema, max_tokens, effort=None):
        self.structured_calls.append(
            {
                "system": system, "user": user, "schema": schema,
                "max_tokens": max_tokens, "effort": effort,
            }
        )
        return self._next(self._structured, "complete_structured")

    def complete_text(self, *, system, user, max_tokens, effort=None):
        self.text_calls.append(
            {
                "system": system, "user": user, "max_tokens": max_tokens,
                "effort": effort,
            }
        )
        return self._next(self._text, "complete_text")

    def _next(self, queue: list, stage: str):
        from app.nlq.llm import LLMResponse, TokenUsage

        if not queue:
            raise AssertionError(f"FakeLLM: unexpected extra call to {stage}")
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        if hasattr(item, "text"):
            return item
        return LLMResponse(
            text=item,
            model=self._model,
            usage=TokenUsage(input_tokens=100, output_tokens=20),
        )


def plan_json(*steps, answerable=True, unsupported_reason=None) -> str:
    """Serialise a planner response the way a model would return it."""
    import json

    payload = {"answerable": answerable, "steps": list(steps)}
    if unsupported_reason is not None:
        payload["unsupported_reason"] = unsupported_reason
    return json.dumps(payload)


def step(operation: str, purpose: str = "because", **params) -> dict:
    return {"purpose": purpose, "request": {"operation": operation, **params}}


@pytest.fixture
def question_service(session_factory):
    """Build a `QuestionService` over the test database with a scripted model.

    `today` is injected so every relative-date assertion is deterministic.
    """
    from datetime import date

    from app.analytics.service import AnalyticsService
    from app.forecasting.service import ForecastService
    from app.nlq.context import ContextBuilder
    from app.nlq.executor import AnalyticsExecutor
    from app.nlq.orchestrator import QuestionService
    from app.nlq.resolution import ProductResolver

    def _build(llm, *, today: date = date(2026, 9, 4), **kwargs):
        resolver = ProductResolver(session_factory)
        forecasts = ForecastService(session_factory)
        return QuestionService(
            llm=llm,
            executor=AnalyticsExecutor(
                analytics=AnalyticsService(session_factory),
                forecasts=forecasts,
                resolver=resolver,
            ),
            context=ContextBuilder(resolver, forecasts, today=today),
            **kwargs,
        )

    return _build
