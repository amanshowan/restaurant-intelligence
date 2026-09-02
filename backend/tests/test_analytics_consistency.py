"""Cross-endpoint reconciliation and edge cases.

Every M3 endpoint slices the same underlying orders a different way. If any two
disagree, at least one is wrong — and the disagreement would show up as a
dashboard whose headline number contradicts its own chart. These tests pin that
down: for one window, all five views must add up to the same totals.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.analytics.service import AnalyticsService
from app.analytics.windows import MAX_RANGE_DAYS, InvalidDateRange
from app.models.enums import Channel, OrderEventType

WINDOW = (date(2026, 8, 1), date(2026, 8, 31))


@pytest.fixture
def analytics(session_factory) -> AnalyticsService:
    return AnalyticsService(session_factory)


@pytest.fixture
def mixed_month(make_order):
    """Payments, discounts and refunds spread across weekdays and channels.

    Deliberately includes a refund in a different channel and on a different
    weekday from its sale, so an endpoint that mishandles refunds diverges from
    the others rather than failing symmetrically.
    """
    make_order("2026-08-03T09:15", net=1250, discount=150, units=3,
               channel=Channel.IN_STORE)                       # Monday
    make_order("2026-08-04T12:30", net=800, units=2, channel=Channel.DELIVERY)
    make_order("2026-08-06T18:45", net=430, discount=70, units=1,
               channel=Channel.ONLINE)                          # Thursday
    make_order("2026-08-08T11:00", net=2100, units=5, channel=Channel.IN_STORE)
    make_order("2026-08-09T14:20", net=615, units=2, channel=Channel.MIXED)
    make_order("2026-08-15T10:05", net=1500, units=4, channel=Channel.COLLECTION)
    make_order("2026-08-20T16:40", net=-450, units=-1,
               event_type=OrderEventType.REFUND, channel=Channel.DELIVERY)
    make_order("2026-08-23T13:10", net=-120, units=-1,
               event_type=OrderEventType.REFUND, channel=Channel.UNKNOWN)
    make_order("2026-08-31T23:30", net=940, units=2, channel=Channel.IN_STORE)


def _totals(items, net, orders, units):
    return (
        sum(getattr(i, net) for i in items),
        sum(getattr(i, orders) for i in items),
        sum(getattr(i, units) for i in items),
    )


# --- cross-endpoint reconciliation -------------------------------------------


def test_daily_revenue_reconciles_with_overview(analytics, mixed_month):
    _, overview = analytics.overview(*WINDOW)
    series = analytics.revenue(*WINDOW, "day")
    assert _totals(series.buckets, "net_sales_pence", "payment_order_count",
                   "net_units") == (
        overview.net_sales_pence,
        overview.payment_order_count,
        overview.net_units,
    )


def test_weekly_revenue_reconciles_with_overview(analytics, mixed_month):
    _, overview = analytics.overview(*WINDOW)
    series = analytics.revenue(*WINDOW, "week")
    assert _totals(series.buckets, "net_sales_pence", "payment_order_count",
                   "net_units") == (
        overview.net_sales_pence,
        overview.payment_order_count,
        overview.net_units,
    )


def test_daily_and_weekly_series_agree_with_each_other(analytics, mixed_month):
    daily = analytics.revenue(*WINDOW, "day").buckets
    weekly = analytics.revenue(*WINDOW, "week").buckets
    assert sum(b.net_sales_pence for b in daily) == sum(
        b.net_sales_pence for b in weekly
    )


def test_weekday_rows_reconcile_with_overview(analytics, mixed_month):
    _, overview = analytics.overview(*WINDOW)
    _, weekdays = analytics.day_of_week(*WINDOW)
    assert len(weekdays) == 7
    assert _totals(weekdays, "net_sales_pence", "payment_order_count",
                   "net_units") == (
        overview.net_sales_pence,
        overview.payment_order_count,
        overview.net_units,
    )


def test_peak_hour_cells_reconcile_with_overview(analytics, mixed_month):
    _, overview = analytics.overview(*WINDOW)
    _, grid = analytics.peak_hours(*WINDOW)
    assert len(grid.cells) == 168
    assert _totals(grid.cells, "net_sales_pence", "payment_order_count",
                   "net_units") == (
        overview.net_sales_pence,
        overview.payment_order_count,
        overview.net_units,
    )


def test_channel_rows_reconcile_with_overview(analytics, mixed_month):
    _, overview = analytics.overview(*WINDOW)
    _, shares = analytics.channel_mix(*WINDOW)
    totals = [s.totals for s in shares]
    assert _totals(totals, "net_sales_pence", "payment_order_count",
                   "net_units") == (
        overview.net_sales_pence,
        overview.payment_order_count,
        overview.net_units,
    )


def test_gross_and_discounts_reconcile_across_daily_buckets(analytics, mixed_month):
    _, overview = analytics.overview(*WINDOW)
    buckets = analytics.revenue(*WINDOW, "day").buckets
    assert sum(b.gross_sales_pence for b in buckets) == overview.gross_sales_pence
    assert sum(b.discounts_pence for b in buckets) == overview.discounts_pence
    assert overview.gross_sales_pence - overview.discounts_pence == (
        overview.net_sales_pence
    )


def test_refund_count_is_the_difference_between_all_orders_and_payments(
    analytics, mixed_month
):
    """The mixed month has two refunds; no endpoint counts them as orders."""
    _, overview = analytics.overview(*WINDOW)
    _, weekdays = analytics.day_of_week(*WINDOW)
    assert overview.refund_event_count == 2
    assert overview.payment_order_count == 7
    assert sum(w.payment_order_count for w in weekdays) == 7


def test_all_five_endpoints_agree_on_one_window(analytics, mixed_month):
    """The single assertion that matters: every view, one set of totals."""
    _, overview = analytics.overview(*WINDOW)
    expected = (
        overview.net_sales_pence,
        overview.payment_order_count,
        overview.net_units,
    )
    _, weekdays = analytics.day_of_week(*WINDOW)
    _, grid = analytics.peak_hours(*WINDOW)
    _, shares = analytics.channel_mix(*WINDOW)

    views = {
        "daily": analytics.revenue(*WINDOW, "day").buckets,
        "weekly": analytics.revenue(*WINDOW, "week").buckets,
        "weekday": weekdays,
        "peak_hours": grid.cells,
        "channels": [s.totals for s in shares],
    }
    for name, rows in views.items():
        assert _totals(rows, "net_sales_pence", "payment_order_count",
                       "net_units") == expected, f"{name} disagrees with overview"


# --- edge cases --------------------------------------------------------------


def test_completely_empty_range_is_consistent_everywhere(analytics):
    _, overview = analytics.overview(*WINDOW)
    assert (overview.net_sales_pence, overview.payment_order_count) == (0, 0)
    assert overview.average_order_value_pence == 0

    assert len(analytics.revenue(*WINDOW, "day").buckets) == 31
    _, weekdays = analytics.day_of_week(*WINDOW)
    assert len(weekdays) == 7 and all(w.net_sales_pence == 0 for w in weekdays)
    _, grid = analytics.peak_hours(*WINDOW)
    assert len(grid.cells) == 168 and grid.peak_payment_order_count == 0
    _, shares = analytics.channel_mix(*WINDOW)
    assert shares == []


def test_single_day_range(analytics, make_order):
    make_order("2026-08-15T12:00", net=500, units=2)
    day = (date(2026, 8, 15), date(2026, 8, 15))
    _, overview = analytics.overview(*day)
    assert overview.net_sales_pence == 500
    assert len(analytics.revenue(*day, "day").buckets) == 1
    _, weekdays = analytics.day_of_week(*day)
    assert weekdays[5].net_sales_pence == 500        # Saturday


def test_leap_day(analytics, make_order):
    """29 February 2028. GMT, so no offset complications — just the date."""
    make_order("2028-02-29T12:00", net=700, units=1)
    leap = (date(2028, 2, 29), date(2028, 2, 29))
    _, overview = analytics.overview(*leap)
    assert overview.net_sales_pence == 700
    (bucket,) = analytics.revenue(*leap, "day").buckets
    assert bucket.period_start == date(2028, 2, 29)

    february = analytics.revenue(date(2028, 2, 1), date(2028, 2, 29), "day")
    assert len(february.buckets) == 29


def test_maximum_366_day_range_is_accepted(analytics, make_order):
    make_order("2026-01-01T12:00", net=100)
    start = date(2026, 1, 1)
    end = start + timedelta(days=MAX_RANGE_DAYS - 1)
    series = analytics.revenue(start, end, "day")
    assert len(series.buckets) == MAX_RANGE_DAYS
    assert sum(b.net_sales_pence for b in series.buckets) == 100


def test_367_day_range_is_rejected(analytics):
    start = date(2026, 1, 1)
    with pytest.raises(InvalidDateRange, match="exceeds the maximum"):
        analytics.overview(start, start + timedelta(days=MAX_RANGE_DAYS))


@pytest.mark.parametrize(
    "method", ["overview", "day_of_week", "peak_hours", "channel_mix"]
)
def test_reversed_range_rejected_by_every_endpoint(analytics, method):
    with pytest.raises(InvalidDateRange, match="must not be before"):
        getattr(analytics, method)(date(2026, 8, 31), date(2026, 8, 1))


def test_reversed_range_rejected_by_revenue(analytics):
    with pytest.raises(InvalidDateRange):
        analytics.revenue(date(2026, 8, 31), date(2026, 8, 1), "day")


# --- timezone boundaries -----------------------------------------------------


def test_bst_start_boundary_across_all_endpoints(analytics, make_order):
    """00:30 BST on 1 Aug is 23:30 UTC on 31 Jul. It belongs to August."""
    make_order("2026-08-01T00:30", net=1000, units=1)          # Saturday
    make_order("2026-07-31T23:30", net=999, units=1)           # must be excluded

    _, overview = analytics.overview(*WINDOW)
    assert overview.net_sales_pence == 1000

    (first,) = [b for b in analytics.revenue(*WINDOW, "day").buckets
                if b.net_sales_pence]
    assert first.period_start == date(2026, 8, 1)

    _, weekdays = analytics.day_of_week(*WINDOW)
    assert weekdays[5].net_sales_pence == 1000                 # Saturday

    _, grid = analytics.peak_hours(*WINDOW)
    hot = [c for c in grid.cells if c.payment_order_count]
    assert (hot[0].iso_weekday, hot[0].hour) == (6, 0)


def test_gmt_boundary_across_all_endpoints(analytics, make_order):
    """January: zero offset, so local and UTC coincide."""
    january = (date(2026, 1, 1), date(2026, 1, 31))
    make_order("2026-01-01T00:30", net=100, units=1)           # Thursday
    make_order("2025-12-31T23:30", net=999, units=1)           # excluded

    _, overview = analytics.overview(*january)
    assert overview.net_sales_pence == 100

    _, grid = analytics.peak_hours(*january)
    hot = [c for c in grid.cells if c.payment_order_count]
    assert (hot[0].iso_weekday, hot[0].hour) == (4, 0)


def test_october_fallback_repeated_local_hour(analytics, session_factory):
    """The hard case: two DISTINCT UTC instants that map to the same local
    wall-clock hour on 25 October 2026, when 01:00-02:00 BST happens twice.

    Both must land in the same local hour bucket, and both must count.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.models import Order
    from app.models.enums import Channel

    UTC = ZoneInfo("UTC")
    # 00:30Z is 01:30 BST (first pass); 01:30Z is 01:30 GMT (second pass).
    instants = [
        datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
        datetime(2026, 10, 25, 1, 30, tzinfo=UTC),
    ]
    with session_factory() as s:
        for i, moment in enumerate(instants):
            s.add(Order(
                source="square", source_order_id=f"TX-FOLD-{i}",
                occurred_at=moment, channel=Channel.IN_STORE,
                event_type=OrderEventType.PAYMENT,
                gross_amount=100, discount_amount=0, net_amount=100, item_count=1,
            ))
        s.commit()

    october = (date(2026, 10, 1), date(2026, 10, 31))
    _, overview = analytics.overview(*october)
    assert overview.net_sales_pence == 200
    assert overview.payment_order_count == 2

    _, grid = analytics.peak_hours(*october)
    hot = [c for c in grid.cells if c.payment_order_count]
    assert len(hot) == 1, "both instants share one local hour bucket"
    assert (hot[0].iso_weekday, hot[0].hour) == (7, 1)     # Sunday 01:00
    assert hot[0].payment_order_count == 2

    (day,) = [b for b in analytics.revenue(*october, "day").buckets
              if b.payment_order_count]
    assert day.period_start == date(2026, 10, 25)


def test_october_transition_window_reconciles(analytics, make_order):
    october = (date(2026, 10, 1), date(2026, 10, 31))
    make_order("2026-10-24T23:30", net=100, units=1)
    make_order("2026-10-26T00:30", net=200, units=1)
    make_order("2026-10-31T23:30", net=300, units=1)

    _, overview = analytics.overview(*october)
    _, grid = analytics.peak_hours(*october)
    _, weekdays = analytics.day_of_week(*october)
    assert overview.net_sales_pence == 600
    assert sum(c.net_sales_pence for c in grid.cells) == 600
    assert sum(w.net_sales_pence for w in weekdays) == 600
    assert len(analytics.revenue(*october, "day").buckets) == 31


# --- degenerate financial windows --------------------------------------------


def test_refund_only_window(analytics, make_order):
    make_order("2026-08-10T10:00", net=-500, units=-1,
               event_type=OrderEventType.REFUND, channel=Channel.DELIVERY)
    _, overview = analytics.overview(*WINDOW)
    assert overview.net_sales_pence == -500
    assert overview.payment_order_count == 0
    assert overview.refund_event_count == 1
    assert overview.net_units == -1
    assert overview.average_order_value_pence == 0

    _, shares = analytics.channel_mix(*WINDOW)
    assert shares[0].share_of_net_sales_percent is None
    assert shares[0].share_of_payment_orders_percent is None

    _, weekdays = analytics.day_of_week(*WINDOW)
    assert sum(w.net_sales_pence for w in weekdays) == -500
    assert all(w.average_order_value_pence == 0 for w in weekdays)


def test_zero_net_sales_window_with_real_activity(analytics, make_order):
    """A sale fully cancelled by a refund: net zero, but not an empty period."""
    make_order("2026-08-10T10:00", net=500, units=1, channel=Channel.IN_STORE)
    make_order("2026-08-11T10:00", net=-500, units=-1,
               event_type=OrderEventType.REFUND, channel=Channel.IN_STORE)

    _, overview = analytics.overview(*WINDOW)
    assert overview.net_sales_pence == 0
    assert overview.payment_order_count == 1
    assert overview.refund_event_count == 1
    assert overview.net_units == 0
    assert overview.average_order_value_pence == 0

    _, shares = analytics.channel_mix(*WINDOW)
    assert len(shares) == 1
    # Share of a zero total is undefined; share of orders is still meaningful.
    assert shares[0].share_of_net_sales_percent is None
    assert shares[0].share_of_payment_orders_percent == 100.0
