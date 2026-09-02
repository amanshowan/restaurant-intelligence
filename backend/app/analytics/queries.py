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

from sqlalchemy import Date, Integer, cast, func, select
from sqlalchemy.orm import Session

from app.analytics.windows import QueryWindow
from app.config import settings
from app.models import Order
from app.models.enums import Channel, OrderEventType

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
        return _mean_pence(self.net_sales_pence, self.payment_order_count)


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


# --- weekday, hour and channel breakdowns ------------------------------------
#
# Weekday and hour are both extracted from the LOCAL timestamp. Using UTC would
# put every order between midnight and 01:00 BST on the previous day, and shift
# the whole trading profile an hour to the left for seven months of the year —
# producing a plausible-looking peak-hour chart that is simply wrong.

def _iso_weekday():
    """1 = Monday … 7 = Sunday, matching ISO-8601 and date.isoweekday()."""
    return cast(func.extract("isodow", _local_timestamp()), Integer)


def _local_hour():
    """Hour of the local trading day, 0-23."""
    return cast(func.extract("hour", _local_timestamp()), Integer)


@dataclass(frozen=True)
class WeekdayTotals:
    iso_weekday: int
    net_sales_pence: int = 0
    payment_order_count: int = 0
    net_units: int = 0

    @property
    def average_order_value_pence(self) -> int:
        return _mean_pence(self.net_sales_pence, self.payment_order_count)


@dataclass(frozen=True)
class HourCellTotals:
    iso_weekday: int
    hour: int
    payment_order_count: int = 0
    net_sales_pence: int = 0
    net_units: int = 0


@dataclass(frozen=True)
class ChannelTotals:
    channel: Channel
    net_sales_pence: int = 0
    payment_order_count: int = 0
    net_units: int = 0

    @property
    def average_order_value_pence(self) -> int:
        return _mean_pence(self.net_sales_pence, self.payment_order_count)


def _mean_pence(total: int, count: int) -> int:
    """Rounded half away from zero, so refund-heavy periods round symmetrically."""
    if count == 0:
        return 0
    sign = -1 if total < 0 else 1
    return sign * ((abs(total) + count // 2) // count)


def _window_filter(window: QueryWindow):
    """Sargable range predicate on the raw indexed column."""
    return (
        Order.occurred_at >= window.start_utc,
        Order.occurred_at < window.end_utc,
    )


def fetch_day_of_week(session: Session, window: QueryWindow) -> dict[int, WeekdayTotals]:
    """Totals per ISO weekday, aggregated across every such day in the window."""
    weekday = _iso_weekday().label("iso_weekday")
    rows = session.execute(
        select(weekday, *_measures())
        .where(*_window_filter(window))
        .group_by(weekday)
        .order_by(weekday)
    ).all()
    return {
        row.iso_weekday: WeekdayTotals(
            iso_weekday=row.iso_weekday,
            net_sales_pence=row.net_sales_pence,
            payment_order_count=row.payment_order_count,
            net_units=row.net_units,
        )
        for row in rows
    }


def fetch_peak_hours(
    session: Session, window: QueryWindow
) -> dict[tuple[int, int], HourCellTotals]:
    """Totals per (ISO weekday, local hour) cell."""
    weekday = _iso_weekday().label("iso_weekday")
    hour = _local_hour().label("hour")
    rows = session.execute(
        select(weekday, hour, *_measures())
        .where(*_window_filter(window))
        .group_by(weekday, hour)
        .order_by(weekday, hour)
    ).all()
    return {
        (row.iso_weekday, row.hour): HourCellTotals(
            iso_weekday=row.iso_weekday,
            hour=row.hour,
            payment_order_count=row.payment_order_count,
            net_sales_pence=row.net_sales_pence,
            net_units=row.net_units,
        )
        for row in rows
    }


def fetch_channel_mix(session: Session, window: QueryWindow) -> list[ChannelTotals]:
    """Totals per canonical channel, richest first.

    Channels are never merged: `online`, `mixed` and `unknown` stay distinct
    from the three they might casually be folded into, because each records a
    different fact about how the order arrived (ARCHITECTURE.md §4).
    """
    rows = session.execute(
        select(Order.channel, *_measures())
        .where(*_window_filter(window))
        .group_by(Order.channel)
        .order_by(func.coalesce(func.sum(Order.net_amount), 0).desc(), Order.channel)
    ).all()
    return [
        ChannelTotals(
            channel=row.channel,
            net_sales_pence=row.net_sales_pence,
            payment_order_count=row.payment_order_count,
            net_units=row.net_units,
        )
        for row in rows
    ]
