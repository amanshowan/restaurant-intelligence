"""Translating user-facing calendar dates into UTC query windows.

Users think in local calendar days — "August" means 1 to 31 August as the till
saw them. The database stores instants in UTC. Bridging the two is the single
most error-prone part of this codebase, so it lives in one place with one rule
(ARCHITECTURE.md §4):

    occurred_at >= local_midnight(start_date)              inclusive
    occurred_at <  local_midnight(end_date + 1 day)        exclusive

Half-open, not closed: comparing `occurred_at <= end_date` coerces the date to
midnight and silently discards almost the whole final day.

Local-then-convert, not a fixed offset: the UK is UTC+1 in summer and UTC+0 in
winter, so the same calendar range maps to different instants by season, and a
range spanning the switch has boundaries with DIFFERENT offsets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.config import BUSINESS_TZ, UTC

#: Upper bound on any single analytics request. Bounds the work a single
#: request can ask the database for, and the size of the response.
MAX_RANGE_DAYS = 366


class InvalidDateRange(ValueError):
    """The requested range is reversed or larger than the allowed maximum."""


@dataclass(frozen=True)
class QueryWindow:
    """An inclusive local date range and its half-open UTC equivalent."""

    start_date: date
    end_date: date
    start_utc: datetime
    end_utc: datetime

    @property
    def days(self) -> int:
        return (self.end_date - self.start_date).days + 1


def local_midnight_utc(day: date) -> datetime:
    """Midnight on `day` in the business's timezone, as a UTC instant."""
    return datetime.combine(day, datetime.min.time(), tzinfo=BUSINESS_TZ).astimezone(UTC)


def build_window(start_date: date, end_date: date) -> QueryWindow:
    if end_date < start_date:
        raise InvalidDateRange(
            f"end_date ({end_date}) must not be before start_date ({start_date})"
        )

    span = (end_date - start_date).days + 1
    if span > MAX_RANGE_DAYS:
        raise InvalidDateRange(
            f"requested range of {span} days exceeds the maximum of "
            f"{MAX_RANGE_DAYS} days"
        )

    return QueryWindow(
        start_date=start_date,
        end_date=end_date,
        start_utc=local_midnight_utc(start_date),
        end_utc=local_midnight_utc(end_date + timedelta(days=1)),
    )


def week_start(day: date) -> date:
    """Monday of the week containing `day`.

    Matches PostgreSQL's `date_trunc('week', ...)`, which is ISO Monday-based,
    so buckets generated here line up with buckets grouped in SQL.
    """
    return day - timedelta(days=day.weekday())


def day_buckets(window: QueryWindow) -> list[date]:
    return [
        window.start_date + timedelta(days=offset) for offset in range(window.days)
    ]


def week_buckets(window: QueryWindow) -> list[date]:
    """Week-start dates covering the window.

    The first bucket may begin before `start_date` when the range does not
    start on a Monday — a partial week is reported under the Monday it
    belongs to rather than being silently split.
    """
    buckets: list[date] = []
    cursor = week_start(window.start_date)
    while cursor <= window.end_date:
        buckets.append(cursor)
        cursor += timedelta(days=7)
    return buckets
