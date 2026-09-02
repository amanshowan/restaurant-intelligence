"""Analytics service: window handling, query dispatch and calendar padding.

Sits between the routes and the SQL so that handlers stay thin and the
date/timezone rules live in one testable place.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Literal

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
from app.analytics import products as product_queries
from app.analytics.products import DEFAULT_KINDS, ProductBucket, ProductTotals
from app.analytics.windows import (
    QueryWindow,
    build_window,
    day_buckets,
    week_buckets,
)
from app.models.enums import ProductKind


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


ProductSort = Literal["net_sales", "gross_sales", "net_units", "discounts"]

_SORT_KEYS: dict[ProductSort, Callable[[ProductTotals], int]] = {
    "net_sales": lambda p: p.net_sales_pence,
    "gross_sales": lambda p: p.gross_sales_pence,
    "net_units": lambda p: p.net_units,
    "discounts": lambda p: p.discounts_pence,
}


class MovementStatus(str, Enum):
    """Why a percentage change is or is not defined.

    Describes the arithmetic, not the business. Nothing here says a product is
    performing well or badly — that judgement needs cost data we do not hold.
    """

    #: Previous period was positive, so a percentage change is meaningful.
    #: This includes a fall to zero, which is a well-defined -100%.
    COMPARABLE = "comparable"
    #: Nothing in the previous period, something in this one. No percentage:
    #: growth from zero is not infinite, it is undefined.
    NEW_IN_PERIOD = "new_in_period"
    #: Previous total was zero or negative, so there is no base to divide by.
    NOT_COMPARABLE = "not_comparable"


@dataclass(frozen=True)
class ProductShare:
    totals: ProductTotals
    share_of_net_sales_percent: float | None
    share_of_units_percent: float | None


@dataclass(frozen=True)
class ProductRanking:
    window: QueryWindow
    kinds: tuple[ProductKind, ...]
    sort: ProductSort
    products: list[ProductShare]
    total_net_sales_pence: int
    total_net_units: int


@dataclass(frozen=True)
class ProductTrend:
    window: QueryWindow
    granularity: Granularity
    product: ProductTotals
    buckets: list[ProductBucket]


@dataclass(frozen=True)
class ProductMovement:
    product_id: int
    name: str
    variation: str
    kind: ProductKind
    current_net_sales_pence: int
    previous_net_sales_pence: int
    current_net_units: int
    previous_net_units: int
    status: MovementStatus

    @property
    def net_sales_change_pence(self) -> int:
        return self.current_net_sales_pence - self.previous_net_sales_pence

    @property
    def net_units_change(self) -> int:
        return self.current_net_units - self.previous_net_units

    @property
    def net_sales_percent_change(self) -> float | None:
        """None unless the previous period was positive.

        A product with no previous sales has not grown by infinity, and one
        with a negative previous total (refunds only) has no sensible base.
        """
        if self.status is not MovementStatus.COMPARABLE:
            return None
        return round(
            self.net_sales_change_pence * 100 / self.previous_net_sales_pence, 2
        )


@dataclass(frozen=True)
class ProductMovers:
    window: QueryWindow
    previous_window: QueryWindow
    kinds: tuple[ProductKind, ...]
    movements: list[ProductMovement]


def previous_window(window: QueryWindow) -> QueryWindow:
    """The equal-length local date range immediately preceding `window`.

    17 requested days compare against the 17 days that ended the day before the
    range opened. Calendar days, not a fixed number of hours, so a comparison
    spanning a DST change still lines up day-for-day.
    """
    length = window.days
    end = window.start_date - timedelta(days=1)
    return build_window(end - timedelta(days=length - 1), end)


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

    # -- products -------------------------------------------------------------

    def _product_totals(
        self, window: QueryWindow, kinds: tuple[ProductKind, ...]
    ) -> list[ProductTotals]:
        with self._session_factory() as session:
            return product_queries.fetch_product_totals(session, window, kinds)

    def products(
        self,
        start_date: date,
        end_date: date,
        *,
        kinds: tuple[ProductKind, ...] = DEFAULT_KINDS,
        sort: ProductSort = "net_sales",
        limit: int | None = None,
    ) -> ProductRanking:
        """Ranked product variations with their share of the filtered set.

        Shares are computed over EVERY matching product before `limit` is
        applied, so a top-10 list still shows each product's share of the whole
        menu rather than of the ten shown.
        """
        window = build_window(start_date, end_date)
        totals = self._product_totals(window, kinds)

        total_net = sum(t.net_sales_pence for t in totals)
        total_units = sum(t.net_units for t in totals)

        ranked = sorted(
            totals,
            key=lambda t: (-_SORT_KEYS[sort](t), t.name, t.variation),
        )
        if limit is not None:
            ranked = ranked[:limit]

        return ProductRanking(
            window=window,
            kinds=kinds,
            sort=sort,
            total_net_sales_pence=total_net,
            total_net_units=total_units,
            products=[
                ProductShare(
                    totals=t,
                    share_of_net_sales_percent=(
                        _percent(t.net_sales_pence, total_net) if total_net > 0 else None
                    ),
                    share_of_units_percent=(
                        _percent(t.net_units, total_units) if total_units > 0 else None
                    ),
                )
                for t in ranked
            ],
        )

    def product_trend(
        self,
        product_id: int,
        start_date: date,
        end_date: date,
        granularity: Granularity,
    ) -> ProductTrend | None:
        """None when the product id does not exist, so the route can 404."""
        window = build_window(start_date, end_date)
        with self._session_factory() as session:
            product = product_queries.product_exists(session, product_id)
            if product is None:
                return None
            found = product_queries.fetch_product_trend(
                session, window, product_id, granularity
            )

        scaffold = week_buckets(window) if granularity == "week" else day_buckets(window)
        buckets = [
            found.get(b, ProductBucket(period_start=b)) for b in scaffold
        ]
        totals = ProductTotals(
            product_id=product.id,
            name=product.name,
            variation=product.variation,
            kind=product.kind,
            gross_sales_pence=sum(b.gross_sales_pence for b in buckets),
            discounts_pence=sum(b.discounts_pence for b in buckets),
            net_sales_pence=sum(b.net_sales_pence for b in buckets),
            net_units=sum(b.net_units for b in buckets),
            payment_order_count=sum(b.payment_order_count for b in buckets),
        )
        return ProductTrend(
            window=window, granularity=granularity, product=totals, buckets=buckets
        )

    def product_movers(
        self,
        start_date: date,
        end_date: date,
        *,
        kinds: tuple[ProductKind, ...] = DEFAULT_KINDS,
        limit: int | None = None,
    ) -> ProductMovers:
        """Current period against the equal-length period immediately before it.

        Two aggregate queries, one per window, merged by product id. Products
        present in either period appear, so something that vanished is as
        visible as something that appeared.
        """
        window = build_window(start_date, end_date)
        prior = previous_window(window)

        current = {t.product_id: t for t in self._product_totals(window, kinds)}
        earlier = {t.product_id: t for t in self._product_totals(prior, kinds)}

        movements = []
        for product_id in current.keys() | earlier.keys():
            now = current.get(product_id)
            before = earlier.get(product_id)
            identity = now or before
            current_net = now.net_sales_pence if now else 0
            previous_net = before.net_sales_pence if before else 0

            if previous_net > 0:
                status = MovementStatus.COMPARABLE
            elif previous_net == 0 and current_net != 0:
                status = MovementStatus.NEW_IN_PERIOD
            else:
                status = MovementStatus.NOT_COMPARABLE

            movements.append(
                ProductMovement(
                    product_id=product_id,
                    name=identity.name,
                    variation=identity.variation,
                    kind=identity.kind,
                    current_net_sales_pence=current_net,
                    previous_net_sales_pence=previous_net,
                    current_net_units=now.net_units if now else 0,
                    previous_net_units=before.net_units if before else 0,
                    status=status,
                )
            )

        # Largest absolute movement first — gains and losses both matter, and
        # neither is labelled good or bad.
        movements.sort(
            key=lambda m: (-abs(m.net_sales_change_pence), m.name, m.variation)
        )
        if limit is not None:
            movements = movements[:limit]

        return ProductMovers(
            window=window, previous_window=prior, kinds=kinds, movements=movements
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
