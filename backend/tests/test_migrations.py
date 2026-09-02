"""Migration round-trips, including against a populated database.

Downgrades are the least-exercised code in any project: they are written by a
generator, rarely run, and typically only ever tested against an empty schema.
The populated-database test below is the one that matters — an earlier version
of f4fdc42bb63b passed on an empty table and failed on any database holding
more than one import batch.

These tests move the shared database between revisions, so each one restores
head in a finally block.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.db import engine

HEAD = "4f359908b385"
BEFORE_EVOLUTION = "c52565f1e614"


@pytest.fixture
def alembic_config(database) -> Config:
    """Alembic config, with the schema guaranteed to be at head afterwards."""
    config = Config("alembic.ini")
    try:
        yield config
    finally:
        command.upgrade(config, "head")


def current_revision() -> str | None:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def table_names() -> set[str]:
    return set(inspect(engine).get_table_names())


def column_names(table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def seed_batches(count: int, *, files_per_batch: int = 3, with_orphan: bool = False):
    """Create populated import batches, mirroring what the importer writes."""
    roles = ["transactions", "items_detail", "items_summary"]
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE order_items, orders, products, import_files, "
                "import_batches RESTART IDENTITY CASCADE"
            )
        )
        for batch in range(1, count + 1):
            batch_id = conn.execute(
                text(
                    "INSERT INTO import_batches (label, status, imported_at, "
                    "period_start, period_end) VALUES (:l, 'completed', :t, "
                    ":s, :e) RETURNING id"
                ),
                {
                    "l": f"batch-{batch}",
                    "t": datetime(2026, 8, batch, tzinfo=timezone.utc),
                    "s": date(2026, 8, batch),
                    "e": date(2026, 8, batch),
                },
            ).scalar()
            for index in range(files_per_batch):
                conn.execute(
                    text(
                        "INSERT INTO import_files (import_batch_id, role, "
                        "filename, file_checksum, row_count, rows_imported, "
                        "rows_skipped) VALUES (:b, :r, :f, :c, 10, 9, 1)"
                    ),
                    {
                        "b": batch_id,
                        "r": roles[index],
                        "f": f"{roles[index]}-{batch}.csv",
                        "c": f"checksum-{batch}-{roles[index]}",
                    },
                )
        if with_orphan:
            # A FAILED batch, which the importer deliberately records with no
            # ImportFile rows so its checksums stay retryable.
            conn.execute(
                text(
                    "INSERT INTO import_batches (label, status, imported_at, "
                    "error_log) VALUES ('failed-batch', 'failed', :t, 'boom')"
                ),
                {"t": datetime(2026, 8, 9, tzinfo=timezone.utc)},
            )


# --- basic round-trips -------------------------------------------------------


def test_empty_database_base_to_head(alembic_config):
    command.downgrade(alembic_config, "base")
    assert table_names() <= {"alembic_version"}

    command.upgrade(alembic_config, "head")
    assert current_revision() == HEAD
    assert {"import_batches", "import_files", "products", "orders",
            "order_items"} <= table_names()


def test_head_to_base_on_an_empty_database(alembic_config):
    command.downgrade(alembic_config, "base")
    assert current_revision() is None
    assert table_names() <= {"alembic_version"}


def test_no_metadata_drift_at_head(alembic_config):
    """The models and the migrations describe the same schema."""
    command.upgrade(alembic_config, "head")
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db import Base
    import app.models  # noqa: F401  registers every mapper

    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"schema drift: {diff}"


# --- the defect this file exists for ----------------------------------------


def test_downgrade_succeeds_with_multiple_populated_batches(alembic_config):
    """The regression: three batches, nine files, through the evolution
    migration's downgrade. Restoring a constant file_checksum made every row
    collide on the recreated UNIQUE constraint."""
    seed_batches(3)
    command.downgrade(alembic_config, BEFORE_EVOLUTION)

    assert current_revision() == BEFORE_EVOLUTION
    assert "import_files" not in table_names()
    assert {"filename", "file_checksum", "row_count"} <= column_names("import_batches")

    with engine.connect() as conn:
        rows = conn.execute(
            # `label` is dropped by this downgrade, so it cannot be selected.
            text(
                "SELECT filename, file_checksum, row_count "
                "FROM import_batches ORDER BY id"
            )
        ).all()
    assert len(rows) == 3
    checksums = [r.file_checksum for r in rows]
    assert len(set(checksums)) == 3, "UNIQUE (file_checksum) must hold"
    assert all(c for c in checksums), "NOT NULL must hold"


def test_downgrade_recovers_the_real_transactions_file(alembic_config):
    """Values are recovered from import_files, not invented."""
    seed_batches(2)
    command.downgrade(alembic_config, BEFORE_EVOLUTION)

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT filename, file_checksum, row_count FROM import_batches "
                 "ORDER BY id")
        ).all()
    assert [r.filename for r in rows] == ["transactions-1.csv", "transactions-2.csv"]
    assert [r.file_checksum for r in rows] == [
        "checksum-1-transactions", "checksum-2-transactions"
    ]
    assert all(r.row_count == 10 for r in rows)


def test_batch_without_files_gets_an_obviously_synthetic_marker(alembic_config):
    """A FAILED batch has no file rows. It must not be given something that
    looks like a real checksum."""
    seed_batches(2, with_orphan=True)
    command.downgrade(alembic_config, BEFORE_EVOLUTION)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT filename, file_checksum, row_count FROM import_batches "
                 "ORDER BY id DESC LIMIT 1")
        ).one()
    assert row.file_checksum.startswith("downgraded-no-source-file-")
    assert row.filename == "(unknown: batch had no file record)"
    assert row.row_count == 0


def test_unique_constraint_is_enforced_after_downgrade(alembic_config):
    """The restored constraint is real, not merely created."""
    from sqlalchemy.exc import IntegrityError

    seed_batches(2)
    command.downgrade(alembic_config, BEFORE_EVOLUTION)

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO import_batches (filename, file_checksum, "
                    "row_count, status, imported_at) VALUES ('x.csv', "
                    "'checksum-1-transactions', 1, 'completed', now())"
                )
            )


def test_upgrade_again_after_a_populated_downgrade(alembic_config):
    seed_batches(3, with_orphan=True)
    command.downgrade(alembic_config, BEFORE_EVOLUTION)
    command.upgrade(alembic_config, "head")

    assert current_revision() == HEAD
    assert "import_files" in table_names()
    assert {"label", "period_start", "period_end"} <= column_names("import_batches")
    assert "file_checksum" not in column_names("import_batches")
    # The batches survive; their file rows do not, which the migration
    # documents as unavoidable.
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM import_batches")
        ).scalar() == 4


def test_full_base_to_head_round_trip_with_data(alembic_config):
    seed_batches(2)
    command.downgrade(alembic_config, "base")
    assert table_names() <= {"alembic_version"}
    command.upgrade(alembic_config, "head")
    assert current_revision() == HEAD


# --- the newest migration ----------------------------------------------------


def test_line_discount_migration_round_trips(alembic_config):
    """4f359908b385, added most recently, still reverses cleanly."""
    command.upgrade(alembic_config, "head")
    assert "discount_amount" in column_names("order_items")

    command.downgrade(alembic_config, "f4fdc42bb63b")
    assert "discount_amount" not in column_names("order_items")

    command.upgrade(alembic_config, "head")
    assert "discount_amount" in column_names("order_items")


def test_line_discount_column_has_no_server_default(alembic_config):
    """The default exists only to make the NOT NULL addition possible; leaving
    it in place would let an INSERT silently record an unverified zero."""
    command.upgrade(alembic_config, "head")
    column = next(
        c for c in inspect(engine).get_columns("order_items")
        if c["name"] == "discount_amount"
    )
    assert column["default"] is None
    assert column["nullable"] is False
