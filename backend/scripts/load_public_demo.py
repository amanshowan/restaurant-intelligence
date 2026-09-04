"""Load the generated demo year into a database, through the real importer.

WHY A SCRIPT RATHER THAN TWELVE CURL UPLOADS
It calls `SquareImportService` — the same class the HTTP endpoint calls, with
the same validation, deduplication, channel derivation and reconciliation.
Nothing here writes to a sales table directly, and nothing bypasses a check.
What it avoids is twelve multipart uploads of a few megabytes each, which tests
the proxy rather than the importer.

WHY IT REFUSES TO RUN ANYWHERE BUT A DEMO DATABASE
The obvious accident is loading a fictional café's year on top of a real
business's imported data, and the two are indistinguishable once merged. So the
target database name must end in `_demo`, and the URL must not be the one
`DATABASE_URL` points at. There is deliberately NO fallback to `DATABASE_URL`:
inheriting the development database is precisely the outcome being prevented.

Run:  docker compose exec api python scripts/load_public_demo.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

#: The suffix a target database must carry. The whole guard: a name that a
#: production or development database would never plausibly have.
REQUIRED_SUFFIX = "_demo"

DEFAULT_DEMO_URL_ENV = "DEMO_DATABASE_URL"


class UnsafeDemoDatabase(RuntimeError):
    """Refusing to load synthetic data into a database that may hold real data."""


def database_name(url: str) -> str:
    return urlsplit(url).path.lstrip("/")


def resolve_target(explicit: str | None) -> str:
    """The demo database URL, or a refusal.

    Derived from `DATABASE_URL` by swapping the database NAME, so an operator
    does not have to restate credentials — but the result is still checked, and
    still compared against the original.
    """
    development = os.environ.get("DATABASE_URL", "")
    url = explicit or os.environ.get(DEFAULT_DEMO_URL_ENV) or (
        f"{development.rsplit('/', 1)[0]}/restaurant_intelligence{REQUIRED_SUFFIX}"
        if development
        else ""
    )

    if not url:
        raise UnsafeDemoDatabase(
            "no target database. Set DATABASE_URL (so one can be derived) or "
            f"pass --database-url explicitly."
        )

    name = database_name(url)
    if not name.endswith(REQUIRED_SUFFIX):
        raise UnsafeDemoDatabase(
            f"refusing to load demo data into database {name!r}: the name must "
            f"end with {REQUIRED_SUFFIX!r}. This script writes a fictional "
            f"café's trading year, which is indistinguishable from real data "
            f"once merged."
        )
    if development and url == development:
        raise UnsafeDemoDatabase(
            f"the demo target is identical to DATABASE_URL ({name!r}). The "
            f"development database holds imported data and must not be "
            f"overwritten."
        )
    return url


def ensure_database(url: str) -> None:
    """Create the demo database if it does not exist, and start it empty."""
    from sqlalchemy import create_engine, text

    from app.db_url import normalise_database_url

    name = database_name(url)
    # This engine predates Settings, so it normalises the scheme itself.
    maintenance = normalise_database_url(url.rsplit("/", 1)[0] + "/postgres")
    engine = create_engine(maintenance, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": name},
            ).scalar()
            if not exists:
                # The name has already passed the suffix check above, and
                # CREATE DATABASE cannot take a bind parameter.
                conn.execute(text(f'CREATE DATABASE "{name}"'))
                print(f"  created database {name}")
            else:
                print(f"  using existing database {name}")
    finally:
        engine.dispose()


def batches(directory: Path) -> list[tuple[str, Path, Path, Path]]:
    """One (label, transactions, items, summary) per month, chronologically."""
    found = []
    for transactions in sorted(directory.glob("transactions-*.csv")):
        month = transactions.stem.removeprefix("transactions-")
        items = directory / f"items-{month}.csv"
        summary = directory / f"item-sales-summary-{month}.csv"
        if not items.exists() or not summary.exists():
            raise FileNotFoundError(f"incomplete batch for {month} in {directory}")
        found.append((month, transactions, items, summary))
    if not found:
        raise FileNotFoundError(
            f"no generated exports in {directory}. Run "
            f"scripts/generate_public_demo.py first."
        )
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--data-dir", type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "public-demo",
    )
    parser.add_argument(
        "--database-url", default=None,
        help=f"target database; defaults to ${DEFAULT_DEMO_URL_ENV} or a "
             f"'*{REQUIRED_SUFFIX}' database beside DATABASE_URL",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="truncate sales tables before loading, for a repeatable load",
    )
    args = parser.parse_args()

    try:
        target = resolve_target(args.database_url)
    except UnsafeDemoDatabase as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    found = batches(args.data_dir)
    print(f"Loading {len(found)} monthly batches into {database_name(target)}")
    ensure_database(target)

    # Set BEFORE importing anything from `app`: Settings is built at import
    # time and app.db builds its engine from it, so by the time either module
    # has been imported the choice of database is already made.
    os.environ["DATABASE_URL"] = target

    from alembic import command
    from alembic.config import Config

    command.upgrade(Config("alembic.ini"), "head")

    from sqlalchemy import text

    from app.db import SessionLocal, engine
    from app.services.importer import ImportRequest, SquareImportService

    if args.reset:
        with engine.begin() as conn:
            conn.execute(text(
                "TRUNCATE order_items, orders, products, import_files, "
                "import_batches RESTART IDENTITY CASCADE"
            ))
        print("  reset: sales tables truncated")

    service = SquareImportService(SessionLocal)
    reconciled = 0

    for month, transactions, items, summary in found:
        outcome = service.run(
            ImportRequest(
                transactions=transactions, items=items, summary=summary,
                label=f"copper-kettle-{month}",
            )
        )
        report = outcome.reconciliation
        state = "reconciled" if report.matches else "MISMATCH"
        if report.matches:
            reconciled += 1
        print(
            f"  {month}  {outcome.status.value:<9} orders={outcome.orders_created:>5} "
            f"items={outcome.order_items_created:>5} "
            f"net={outcome.net_sales_pence / 100:>10,.2f}  {state}"
        )
        if not report.matches:
            print(f"           {report.describe()}")

    print(f"\n  {reconciled}/{len(found)} months reconciled exactly")
    return 0 if reconciled == len(found) else 1


if __name__ == "__main__":
    raise SystemExit(main())
