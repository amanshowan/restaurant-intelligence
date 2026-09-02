"""Analytics service: window handling, query dispatch and calendar padding.

Sits between the routes and the SQL so that handlers stay thin and the
date/timezone rules live in one testable place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session, sessionmaker

from app.analytics import queries
from app.analytics.queries import Granularity, OverviewTotals, RevenueBucket
from app.analytics.windows import (
    QueryWindow,
    build_window,
    day_buckets,
    week_buckets,
)


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
