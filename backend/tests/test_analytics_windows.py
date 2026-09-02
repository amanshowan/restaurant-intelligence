"""Local-date to UTC window conversion — the project's sharpest edge."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.analytics.windows import (
    InvalidDateRange,
    MAX_RANGE_DAYS,
    build_window,
    day_buckets,
    week_buckets,
    week_start,
)

UTC = ZoneInfo("UTC")


def test_bst_range_converts_with_a_one_hour_offset():
    w = build_window(date(2026, 8, 1), date(2026, 8, 31))
    assert w.start_utc == datetime(2026, 7, 31, 23, 0, tzinfo=UTC)
    assert w.end_utc == datetime(2026, 8, 31, 23, 0, tzinfo=UTC)
    assert w.days == 31


def test_gmt_range_converts_with_no_offset():
    w = build_window(date(2026, 1, 1), date(2026, 1, 31))
    assert w.start_utc == datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    assert w.end_utc == datetime(2026, 2, 1, 0, 0, tzinfo=UTC)


def test_range_spanning_the_dst_switch_has_different_offsets_at_each_end():
    """October straddles BST->GMT: the window is 31 days AND one hour long."""
    w = build_window(date(2026, 10, 1), date(2026, 10, 31))
    assert w.start_utc == datetime(2026, 9, 30, 23, 0, tzinfo=UTC)   # BST, +1
    assert w.end_utc == datetime(2026, 11, 1, 0, 0, tzinfo=UTC)      # GMT, +0
    assert (w.end_utc - w.start_utc).total_seconds() == 31 * 86400 + 3600


def test_window_is_half_open_so_the_final_day_is_included_in_full():
    w = build_window(date(2026, 8, 1), date(2026, 8, 31))
    last_moment = datetime(2026, 8, 31, 23, 59, 59, tzinfo=ZoneInfo("Europe/London"))
    assert w.start_utc <= last_moment.astimezone(UTC) < w.end_utc


def test_single_day_range_is_valid():
    w = build_window(date(2026, 8, 15), date(2026, 8, 15))
    assert w.days == 1
    assert (w.end_utc - w.start_utc).total_seconds() == 86400


def test_reversed_range_is_rejected():
    with pytest.raises(InvalidDateRange, match="must not be before"):
        build_window(date(2026, 8, 31), date(2026, 8, 1))


def test_oversized_range_is_rejected():
    with pytest.raises(InvalidDateRange, match="exceeds the maximum"):
        build_window(date(2026, 1, 1), date(2027, 12, 31))


def test_maximum_range_is_allowed_exactly():
    from datetime import timedelta

    start = date(2026, 1, 1)
    edge = build_window(start, start + timedelta(days=MAX_RANGE_DAYS - 1))
    assert edge.days == MAX_RANGE_DAYS

    with pytest.raises(InvalidDateRange):
        build_window(start, start + timedelta(days=MAX_RANGE_DAYS))


def test_week_start_is_monday():
    assert week_start(date(2026, 8, 5)) == date(2026, 8, 3)   # Wed -> Mon
    assert week_start(date(2026, 8, 3)) == date(2026, 8, 3)   # Mon -> itself
    assert week_start(date(2026, 8, 9)) == date(2026, 8, 3)   # Sun -> Mon


def test_day_buckets_cover_every_date_inclusively():
    buckets = day_buckets(build_window(date(2026, 8, 1), date(2026, 8, 5)))
    assert buckets == [date(2026, 8, d) for d in range(1, 6)]


def test_week_buckets_start_on_the_monday_containing_the_range_start():
    buckets = week_buckets(build_window(date(2026, 8, 5), date(2026, 8, 20)))
    assert buckets == [date(2026, 8, 3), date(2026, 8, 10), date(2026, 8, 17)]
