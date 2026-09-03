"""The canonical daily forecasting series.

One row per LOCAL calendar day, built from the same SQL aggregation the
analytics API already uses (`analytics.queries.fetch_revenue_series`). That
reuse is the point: "daily net sales" must mean exactly one thing across this
codebase. Defining a second version here — even an apparently identical one —
would let the forecast and the dashboard disagree about the same day.

What that inherits, and therefore guarantees:

  * grouping on `occurred_at AT TIME ZONE 'Europe/London'`, so a day is the
    trading day and BST does not shift takings into the previous one;
  * refunds reducing net sales and net units, because both are summed across
    every order and `item_count` is signed;
  * `payment_order_count` restricted to `event_type = payment`, identical to
    `/analytics/overview`, so a refund never inflates volume;
  * aggregation in PostgreSQL — one row per day comes back, never the orders.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from app.analytics import queries
from app.analytics.windows import build_window, day_buckets

#: The measures this commit forecasts. Money stays an integer number of pence.
Target = Literal["net_sales_pence", "payment_order_count", "net_units"]

TARGETS: tuple[Target, ...] = (
    "net_sales_pence",
    "payment_order_count",
    "net_units",
)

#: Human wording for reports.
TARGET_LABELS: dict[Target, str] = {
    "net_sales_pence": "net sales",
    "payment_order_count": "payment orders",
    "net_units": "net units",
}


@dataclass(frozen=True)
class DailyObservation:
    """One local trading day.

    A zero row is a real observation, not a hole. The business may have been
    shut, and a forecaster that treats a closure as missing data will happily
    predict trade on Christmas Day.
    """

    day: date
    net_sales_pence: int = 0
    payment_order_count: int = 0
    net_units: int = 0

    def value(self, target: Target) -> int:
        return getattr(self, target)

    @property
    def traded(self) -> bool:
        """Whether anything at all happened. Net sales alone is not enough: a
        day whose refunds exactly cancel its sales still saw trade."""
        return (
            self.payment_order_count != 0
            or self.net_sales_pence != 0
            or self.net_units != 0
        )


class SeriesIntegrityError(ValueError):
    """The series is not fit to train or evaluate on.

    Raised rather than repaired. A silently patched series produces a model
    that scores well against data the business never saw, and the fault is
    invisible by the time anyone reads the metrics.
    """


def build_daily_series(
    session_factory, start_date: date, end_date: date
) -> list[DailyObservation]:
    """Every calendar day in the inclusive local range, zero-filled.

    `session_factory` matches the convention `AnalyticsService` uses, so this
    composes with the existing dependency wiring and test fixtures.
    """
    window = build_window(start_date, end_date)

    with session_factory() as session:
        found = queries.fetch_revenue_series(session, window, "day")

    # The scaffold, not the result set, decides which days exist. A day absent
    # from `found` had no orders; that is a zero, and it must be visible.
    series = [
        DailyObservation(
            day=day,
            net_sales_pence=found[day].net_sales_pence if day in found else 0,
            payment_order_count=found[day].payment_order_count if day in found else 0,
            net_units=found[day].net_units if day in found else 0,
        )
        for day in day_buckets(window)
    ]

    validate_series(series)
    return series


def validate_series(
    series: Sequence[DailyObservation], *, minimum_days: int = 1
) -> None:
    """Assert the series is usable, or say precisely why it is not."""
    if len(series) < minimum_days:
        raise SeriesIntegrityError(
            f"series has {len(series)} day(s); at least {minimum_days} are required"
        )
    if not series:
        raise SeriesIntegrityError("series is empty")

    seen: set[date] = set()
    previous: date | None = None

    for observation in series:
        day = observation.day

        if day in seen:
            raise SeriesIntegrityError(f"duplicate date in series: {day}")
        seen.add(day)

        if previous is not None:
            if day <= previous:
                raise SeriesIntegrityError(
                    f"series is not in chronological order: {day} follows {previous}"
                )
            if day != previous + timedelta(days=1):
                # After zero-fill there is no legitimate reason for a gap, and
                # a gap silently shifts every lag feature that follows it.
                missing = (day - previous).days - 1
                raise SeriesIntegrityError(
                    f"series has a {missing}-day gap between {previous} and {day}; "
                    "the calendar must be zero-filled, not compacted"
                )
        previous = day

        for target in TARGETS:
            value = observation.value(target)
            if value is None or not isinstance(value, int):
                raise SeriesIntegrityError(
                    f"{day}: {target} is {value!r}, which is not a whole number"
                )

        # Net sales and net units may legitimately be NEGATIVE — a day whose
        # refunds outweigh its sales is a real trading day, and clamping it
        # would hide exactly the days a forecast most needs to explain. An
        # order COUNT cannot be negative: refunds are excluded from it.
        if observation.payment_order_count < 0:
            raise SeriesIntegrityError(
                f"{observation.day}: payment_order_count is "
                f"{observation.payment_order_count}, which cannot be negative"
            )


def values(series: Sequence[DailyObservation], target: Target) -> list[int]:
    """The target as a plain sequence, in chronological order."""
    return [observation.value(target) for observation in series]
