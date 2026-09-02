"""Database maintenance that follows a successful import.

Deliberately separate from the importer: this is housekeeping, not business
logic, and the distinction matters for how failures are treated. A refused
ANALYZE means later queries may be slower for a minute; it does not mean the
revenue we just imported is wrong.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

#: Tables a bulk import materially changes. Fixed identifiers, never derived
#: from request data, so they cannot be an injection vector.
ANALYZED_TABLES: tuple[str, ...] = ("orders", "order_items", "products")


class StatisticsRefreshFailed(Exception):
    """ANALYZE did not complete. Never raised to an API caller."""


def refresh_planner_statistics(
    engine: Engine, tables: tuple[str, ...] = ANALYZED_TABLES
) -> None:
    """Run ANALYZE so the planner has statistics for freshly imported rows.

    A bulk import leaves PostgreSQL with no statistics for the affected tables
    until autovacuum's autoanalyze catches up. In that window the planner has
    nothing to estimate from and falls back to nested loops: the basket
    pair query measured ~1.6s before ANALYZE against ~7ms after. Autovacuum
    closes the gap on its own within roughly a minute, but the first analytics
    request after an import should not have to wait for it.

    This is a planner hint, never a correctness concern — every figure the
    analytics endpoints return is identical either way. Only the plan changes.

    Runs with AUTOCOMMIT and in its own connection, so it neither joins nor
    disturbs the import transaction, which has already committed by the time
    this is called.
    """
    try:
        with engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            for table in tables:
                # Identifiers are module constants; quoted defensively so a
                # future addition cannot become a syntax surprise.
                connection.execute(text(f'ANALYZE "{table}"'))
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see below
        # Anything at all: a lock timeout, a permissions change, the connection
        # dropping. The import has already committed, so the only correct
        # response is to note it and carry on. The connection context manager
        # has already discarded this connection's work.
        raise StatisticsRefreshFailed(str(exc)) from exc


def refresh_planner_statistics_quietly(
    engine: Engine, tables: tuple[str, ...] = ANALYZED_TABLES
) -> bool:
    """Refresh statistics, swallowing any failure. Returns whether it worked.

    Used on the success path of an import: a maintenance failure must never
    turn a completed business import into a failed one, and must never surface
    database internals to an API caller.
    """
    try:
        refresh_planner_statistics(engine, tables)
        return True
    except StatisticsRefreshFailed:
        logger.warning(
            "planner statistics refresh failed after a successful import; "
            "analytics queries may use stale plans until autovacuum catches up",
            exc_info=True,
        )
        return False
