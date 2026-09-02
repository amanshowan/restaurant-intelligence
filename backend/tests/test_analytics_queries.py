"""Aggregation semantics, against real PostgreSQL."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import sessionmaker

from app.analytics.queries import OverviewTotals
from app.analytics.service import AnalyticsService
from app.models.enums import Channel, OrderEventType


@pytest.fixture
def analytics(session_factory) -> AnalyticsService:
    return AnalyticsService(session_factory)


# --- overview maths ----------------------------------------------------------


def test_overview_totals(analytics, make_order):
    make_order("2026-08-10T09:00", net=1000, discount=200, units=2)
    make_order("2026-08-10T12:00", net=500, discount=0, units=1)
    _, t = analytics.overview(date(2026, 8, 1), date(2026, 8, 31))

    assert t.net_sales_pence == 1500
    assert t.discounts_pence == 200
    assert t.gross_sales_pence == 1700           # net + discount
    assert t.gross_sales_pence - t.discounts_pence == t.net_sales_pence
    assert t.payment_order_count == 2
    assert t.refund_event_count == 0
    assert t.net_units == 3
    assert t.average_order_value_pence == 750


def test_refunds_reduce_net_sales_without_increasing_order_count(analytics, make_order):
    make_order("2026-08-10T09:00", net=1000, units=2)
    make_order("2026-08-10T09:30", net=-400, units=-1,
               event_type=OrderEventType.REFUND)
    _, t = analytics.overview(date(2026, 8, 1), date(2026, 8, 31))

    assert t.net_sales_pence == 600              # refund reduces revenue
    assert t.payment_order_count == 1            # but not volume
    assert t.refund_event_count == 1
    assert t.net_units == 1                      # 2 sold - 1 refunded
    assert t.average_order_value_pence == 600    # 600 / 1 paid order


def test_zero_orders_gives_zero_aov_not_an_error(analytics):
    _, t = analytics.overview(date(2026, 8, 1), date(2026, 8, 31))
    assert t == OverviewTotals()
    assert t.average_order_value_pence == 0


def test_aov_rounds_to_the_nearest_penny(analytics, make_order):
    make_order("2026-08-10T09:00", net=100)
    make_order("2026-08-10T10:00", net=100)
    make_order("2026-08-10T11:00", net=101)
    _, t = analytics.overview(date(2026, 8, 1), date(2026, 8, 31))
    assert t.net_sales_pence == 301
    assert t.average_order_value_pence == 100    # 100.33 -> 100


def test_refund_only_period_yields_a_negative_net(analytics, make_order):
    make_order("2026-08-10T09:00", net=-500, units=-1,
               event_type=OrderEventType.REFUND)
    _, t = analytics.overview(date(2026, 8, 1), date(2026, 8, 31))
    assert t.net_sales_pence == -500
    assert t.payment_order_count == 0
    assert t.average_order_value_pence == 0      # no divisor, no crash


# --- date boundaries ---------------------------------------------------------


def test_final_day_is_included_in_full(analytics, make_order):
    """23:59 on the last requested day must be inside the window."""
    make_order("2026-08-31T23:59", net=1000)
    _, t = analytics.overview(date(2026, 8, 1), date(2026, 8, 31))
    assert t.net_sales_pence == 1000


def test_first_moment_of_the_first_day_is_included(analytics, make_order):
    make_order("2026-08-01T00:00", net=1000)
    _, t = analytics.overview(date(2026, 8, 1), date(2026, 8, 31))
    assert t.net_sales_pence == 1000


def test_bst_boundary_a_00_30_order_belongs_to_its_local_day(analytics, make_order):
    """00:30 BST on 1 Aug is 23:30 UTC on 31 JULY. Grouping on UTC would file
    it under July and drop it from an August range entirely."""
    make_order("2026-08-01T00:30", net=1000)
    _, august = analytics.overview(date(2026, 8, 1), date(2026, 8, 31))
    _, july = analytics.overview(date(2026, 7, 1), date(2026, 7, 31))
    assert august.net_sales_pence == 1000
    assert july.net_sales_pence == 0


def test_bst_boundary_excludes_the_last_moment_of_the_previous_day(analytics, make_order):
    make_order("2026-07-31T23:59", net=1000)
    _, august = analytics.overview(date(2026, 8, 1), date(2026, 8, 31))
    assert august.net_sales_pence == 0


def test_gmt_boundary(analytics, make_order):
    """In January the offset is zero, so local and UTC agree."""
    make_order("2026-01-01T00:30", net=1000)
    make_order("2026-01-31T23:30", net=500)
    _, t = analytics.overview(date(2026, 1, 1), date(2026, 1, 31))
    assert t.net_sales_pence == 1500


def test_range_spanning_the_october_dst_transition(analytics, make_order):
    """25 Oct 2026 is the clocks-back Sunday. Orders on both sides of the
    switch must fall in their own local days."""
    make_order("2026-10-24T23:30", net=100)    # BST
    make_order("2026-10-25T01:30", net=200)    # ambiguous hour, first pass
    make_order("2026-10-26T00:30", net=400)    # GMT
    _, t = analytics.overview(date(2026, 10, 1), date(2026, 10, 31))
    assert t.net_sales_pence == 700

    series = analytics.revenue(date(2026, 10, 24), date(2026, 10, 26), "day")
    by_day = {b.period_start: b.net_sales_pence for b in series.buckets}
    assert by_day == {
        date(2026, 10, 24): 100,
        date(2026, 10, 25): 200,
        date(2026, 10, 26): 400,
    }


# --- revenue series ----------------------------------------------------------


def test_daily_series_is_chronological_and_zero_filled(analytics, make_order):
    make_order("2026-08-01T10:00", net=100)
    make_order("2026-08-04T10:00", net=400)
    series = analytics.revenue(date(2026, 8, 1), date(2026, 8, 5), "day")

    assert [b.period_start for b in series.buckets] == [
        date(2026, 8, d) for d in range(1, 6)
    ]
    assert [b.net_sales_pence for b in series.buckets] == [100, 0, 0, 400, 0]
    # A closed day is visible as a zero, not a gap.
    assert all(b.payment_order_count == 0 for b in series.buckets[1:3])


def test_daily_buckets_carry_every_measure(analytics, make_order):
    make_order("2026-08-01T10:00", net=800, discount=200, units=3)
    make_order("2026-08-01T11:00", net=-100, units=-1,
               event_type=OrderEventType.REFUND)
    (bucket,) = analytics.revenue(date(2026, 8, 1), date(2026, 8, 1), "day").buckets

    assert bucket.net_sales_pence == 700
    # 1000 gross on the sale, -100 on the refund.
    assert bucket.gross_sales_pence == 900
    assert bucket.discounts_pence == 200
    assert bucket.gross_sales_pence - bucket.discounts_pence == bucket.net_sales_pence
    assert bucket.payment_order_count == 1
    assert bucket.net_units == 2


def test_weekly_grouping_buckets_by_monday(analytics, make_order):
    make_order("2026-08-05T10:00", net=100)   # Wed, week of Mon 3 Aug
    make_order("2026-08-09T10:00", net=200)   # Sun, same week
    make_order("2026-08-10T10:00", net=400)   # Mon, next week
    series = analytics.revenue(date(2026, 8, 3), date(2026, 8, 16), "week")

    assert [b.period_start for b in series.buckets] == [
        date(2026, 8, 3), date(2026, 8, 10)
    ]
    assert [b.net_sales_pence for b in series.buckets] == [300, 400]


def test_weekly_series_is_zero_filled_too(analytics, make_order):
    make_order("2026-08-03T10:00", net=100)
    series = analytics.revenue(date(2026, 8, 3), date(2026, 8, 23), "week")
    assert [b.net_sales_pence for b in series.buckets] == [100, 0, 0]


def test_weekly_bucket_may_start_before_the_requested_range(analytics, make_order):
    """A partial week is reported under the Monday it belongs to."""
    make_order("2026-08-05T10:00", net=100)
    series = analytics.revenue(date(2026, 8, 5), date(2026, 8, 7), "week")
    assert [b.period_start for b in series.buckets] == [date(2026, 8, 3)]


def test_orders_outside_the_window_are_excluded_from_the_series(analytics, make_order):
    make_order("2026-07-31T10:00", net=999)
    make_order("2026-08-02T10:00", net=100)
    make_order("2026-09-01T10:00", net=999)
    series = analytics.revenue(date(2026, 8, 1), date(2026, 8, 3), "day")
    assert sum(b.net_sales_pence for b in series.buckets) == 100


def test_channel_does_not_affect_totals(analytics, make_order):
    """Every channel contributes to headline revenue; the split comes later."""
    for channel in (Channel.IN_STORE, Channel.DELIVERY, Channel.ONLINE,
                    Channel.COLLECTION, Channel.MIXED):
        make_order("2026-08-10T10:00", net=100, channel=channel)
    _, t = analytics.overview(date(2026, 8, 1), date(2026, 8, 31))
    assert t.net_sales_pence == 500
    assert t.payment_order_count == 5
