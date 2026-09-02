"""SQL aggregations for the analytics layer.

Every figure here is computed by PostgreSQL. Nothing loads order rows into
Python to loop over them (ARCHITECTURE.md §3) — the largest result any of these
returns is one row per calendar bucket.

Two query decisions worth knowing:

**Filtering happens on the raw `occurred_at` column**, never on a function of
it. `WHERE occurred_at >= :lo AND occurred_at < :hi` with UTC bound parameters
is sargable, so it uses `ix_orders_occurred_at`. Writing the filter as
`WHERE (occurred_at AT TIME ZONE 'Europe/London')::date BETWEEN ...` would be
equivalent in meaning but wraps the indexed column in a function call, forcing
a sequential scan.

**Grouping happens on the local timestamp.** `occurred_at AT TIME ZONE
'Europe/London'` converts the stored instant to trading-local wall time before
truncation, so a day's takings means the business's day. Grouping on UTC would
misfile every order between midnight and 01:00 BST into the previous day for
seven months of the year.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.analytics.windows import QueryWindow
from app.config import settings
from app.models import Order
from app.models.enums import OrderEventType

Granularity = Literal["day", "week"]


def _local_timestamp():
    """`occurred_at AT TIME ZONE '<business zone>'` — a naive local timestamp."""
    return func.timezone(settings.business_timezone, Order.occurred_at)


def _bucket_expression(granularity: Granularity):
    local = _local_timestamp()
    if granularity == "week":
        # Monday-based, matching windows.week_start().
        return cast(func.date_trunc("week", local), Date)
    return cast(local, Date)


#: The measures every analytics query reports, defined once.
#:
#: Financial totals span ALL orders: a refund is a negative-value event and must
#: reduce net sales. Order COUNT is restricted to payments, so a refund never
#: inflates volume — the discriminator that makes both true at once is
#: `orders.event_type`.
def _measures():
    return (
        func.coalesce(func.sum(Order.net_amount), 0).label("net_sales_pence"),
        func.coalesce(func.sum(Order.gross_amount), 0).label("gross_sales_pence"),
        func.coalesce(func.sum(Order.discount_amount), 0).label("discounts_pence"),
        func.count()
        .filter(Order.event_type == OrderEventType.PAYMENT)
        .label("payment_order_count"),
        func.count()
        .filter(Order.event_type == OrderEventType.REFUND)
        .label("refund_event_count"),
        # item_count is signed, so summing yields NET units: a refunded unit
        # cancels the sale rather than counting twice.
        func.coalesce(func.sum(Order.item_count), 0).label("net_units"),
    )


@dataclass(frozen=True)
class OverviewTotals:
    net_sales_pence: int = 0
    gross_sales_pence: int = 0
    discounts_pence: int = 0
    payment_order_count: int = 0
    refund_event_count: int = 0
    net_units: int = 0

    @property
    def average_order_value_pence(self) -> int:
        """Net sales per paid order, rounded to the nearest penny.

        Zero paid orders yields 0 rather than raising: an empty period is a
        legitimate answer, not an error.
        """
        if self.payment_order_count == 0:
            return 0
        total, count = self.net_sales_pence, self.payment_order_count
        # Integer arithmetic with explicit half-away-from-zero rounding, so a
        # net-negative period (refund-heavy) rounds symmetrically.
        sign = -1 if total < 0 else 1
        return sign * ((abs(total) + count // 2) // count)


@dataclass(frozen=True)
class RevenueBucket:
    period_start: date
    net_sales_pence: int = 0
    gross_sales_pence: int = 0
    discounts_pence: int = 0
    payment_order_count: int = 0
    net_units: int = 0


def fetch_overview(session: Session, window: QueryWindow) -> OverviewTotals:
    """One row of totals for the whole window."""
    row = session.execute(
        select(*_measures()).where(
            Order.occurred_at >= window.start_utc,
            Order.occurred_at < window.end_utc,
        )
    ).one()
    return OverviewTotals(
        net_sales_pence=row.net_sales_pence,
        gross_sales_pence=row.gross_sales_pence,
        discounts_pence=row.discounts_pence,
        payment_order_count=row.payment_order_count,
        refund_event_count=row.refund_event_count,
        net_units=row.net_units,
    )


def fetch_revenue_series(
    session: Session, window: QueryWindow, granularity: Granularity
) -> dict[date, RevenueBucket]:
    """Aggregates keyed by local bucket start.

    Returns only buckets that contain orders; the caller pads the calendar.
    Padding in Python is deliberate — the scaffold is at most 366 short-lived
    date objects, whereas a `generate_series` LEFT JOIN would complicate the
    query for no measurable gain.
    """
    bucket = _bucket_expression(granularity).label("bucket")
    rows = session.execute(
        select(bucket, *_measures())
        .where(
            Order.occurred_at >= window.start_utc,
            Order.occurred_at < window.end_utc,
        )
        .group_by(bucket)
        .order_by(bucket)
    ).all()

    return {
        row.bucket: RevenueBucket(
            period_start=row.bucket,
            net_sales_pence=row.net_sales_pence,
            gross_sales_pence=row.gross_sales_pence,
            discounts_pence=row.discounts_pence,
            payment_order_count=row.payment_order_count,
            net_units=row.net_units,
        )
        for row in rows
    }
