"""Analytics service: window handling, query dispatch and calendar padding.

Sits between the routes and the SQL so that handlers stay thin and the
date/timezone rules live in one testable place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session, sessionmaker

from app.analytics import queries
from app.analytics.queries import (
    ChannelTotals,
    Granularity,
    HourCellTotals,
    OverviewTotals,
    RevenueBucket,
    WeekdayTotals,
)
from app.models.enums import Channel
from app.analytics.windows import (
    QueryWindow,
    build_window,
    day_buckets,
    week_buckets,
)


#: ISO-8601 weekday numbering, Monday first. Fixed order, always all seven.
ISO_WEEKDAYS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)
WEEKDAY_NAMES: dict[int, str] = {
    1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday",
    5: "Friday", 6: "Saturday", 7: "Sunday",
}
HOURS: tuple[int, ...] = tuple(range(24))


@dataclass(frozen=True)
class ChannelShare:
    """One channel's totals plus its share of the period."""

    totals: ChannelTotals
    #: Percentage of paid orders. None when the period has no paid orders.
    share_of_payment_orders_percent: float | None
    #: Percentage of net sales. None when total net sales is not positive —
    #: a share of zero is undefined, and a share of a NEGATIVE total (a
    #: refund-heavy period) is arithmetically computable but meaningless.
    share_of_net_sales_percent: float | None


@dataclass(frozen=True)
class PeakHourGrid:
    cells: list[HourCellTotals]
    #: Highest payment-order count in any single cell; 0 for an empty period.
    #: Enough on its own to scale a heatmap's colour ramp.
    peak_payment_order_count: int
    #: The busiest cells, most orders first. Ties broken by weekday then hour
    #: so the ordering is deterministic.
    busiest: list[HourCellTotals]


def _percent(part: int, whole: int) -> float:
    return round(part * 100 / whole, 2)


@dataclass(frozen=True)
class RevenueSeries:
    window: QueryWindow
    granularity: Granularity
    buckets: list[RevenueBucket]


class AnalyticsService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def overview(self, start_date: date, end_date: date) -> tuple[QueryWindow, OverviewTotals]:
        window = build_window(start_date, end_date)
        with self._session_factory() as session:
            return window, queries.fetch_overview(session, window)

    def revenue(
        self, start_date: date, end_date: date, granularity: Granularity
    ) -> RevenueSeries:
        window = build_window(start_date, end_date)
        with self._session_factory() as session:
            found = queries.fetch_revenue_series(session, window, granularity)

        # Pad the calendar so a day with no trade is an explicit zero rather
        # than a gap. A missing bucket and a zero bucket mean different things
        # to a chart, and "the shop was shut" should be visible.
        scaffold = week_buckets(window) if granularity == "week" else day_buckets(window)
        buckets = [
            found.get(bucket, RevenueBucket(period_start=bucket)) for bucket in scaffold
        ]
        return RevenueSeries(window=window, granularity=granularity, buckets=buckets)

    def day_of_week(
        self, start_date: date, end_date: date
    ) -> tuple[QueryWindow, list[WeekdayTotals]]:
        """Always seven rows, Monday to Sunday, zero-filled."""
        window = build_window(start_date, end_date)
        with self._session_factory() as session:
            found = queries.fetch_day_of_week(session, window)
        return window, [
            found.get(day, WeekdayTotals(iso_weekday=day)) for day in ISO_WEEKDAYS
        ]

    def peak_hours(
        self, start_date: date, end_date: date, busiest_limit: int = 5
    ) -> tuple[QueryWindow, PeakHourGrid]:
        """A full 7x24 grid, zero-filled, so the shape is stable for a heatmap."""
        window = build_window(start_date, end_date)
        with self._session_factory() as session:
            found = queries.fetch_peak_hours(session, window)

        cells = [
            found.get((day, hour), HourCellTotals(iso_weekday=day, hour=hour))
            for day in ISO_WEEKDAYS
            for hour in HOURS
        ]
        ranked = sorted(
            (c for c in cells if c.payment_order_count > 0),
            key=lambda c: (-c.payment_order_count, c.iso_weekday, c.hour),
        )
        return window, PeakHourGrid(
            cells=cells,
            peak_payment_order_count=ranked[0].payment_order_count if ranked else 0,
            busiest=ranked[:busiest_limit],
        )

    def channel_mix(
        self, start_date: date, end_date: date
    ) -> tuple[QueryWindow, list[ChannelShare]]:
        """Every channel present in the window, richest first, never merged."""
        window = build_window(start_date, end_date)
        with self._session_factory() as session:
            totals = queries.fetch_channel_mix(session, window)

        total_orders = sum(t.payment_order_count for t in totals)
        total_net = sum(t.net_sales_pence for t in totals)

        return window, [
            ChannelShare(
                totals=t,
                share_of_payment_orders_percent=(
                    _percent(t.payment_order_count, total_orders)
                    if total_orders > 0
                    else None
                ),
                share_of_net_sales_percent=(
                    _percent(t.net_sales_pence, total_net) if total_net > 0 else None
                ),
            )
            for t in totals
        ]
