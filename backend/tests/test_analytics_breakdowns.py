"""Weekday, peak-hour and channel-mix aggregation."""

from __future__ import annotations

from datetime import date

import pytest

from app.analytics.service import AnalyticsService, WEEKDAY_NAMES
from app.models.enums import Channel, OrderEventType

AUG = (date(2026, 8, 1), date(2026, 8, 31))


@pytest.fixture
def analytics(session_factory) -> AnalyticsService:
    return AnalyticsService(session_factory)


# --- day of week -------------------------------------------------------------


def test_weekdays_are_always_monday_to_sunday_in_order(analytics):
    _, weekdays = analytics.day_of_week(*AUG)
    assert [w.iso_weekday for w in weekdays] == [1, 2, 3, 4, 5, 6, 7]
    assert [WEEKDAY_NAMES[w.iso_weekday] for w in weekdays] == [
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
    ]


def test_empty_weekdays_are_explicit_zero_rows(analytics, make_order):
    make_order("2026-08-03T10:00", net=500)      # a Monday
    _, weekdays = analytics.day_of_week(*AUG)
    assert len(weekdays) == 7
    assert weekdays[0].net_sales_pence == 500
    assert all(w.net_sales_pence == 0 for w in weekdays[1:])
    assert all(w.average_order_value_pence == 0 for w in weekdays[1:])


def test_weekday_aggregates_across_every_occurrence(analytics, make_order):
    """All the Mondays in the range are summed into one row."""
    for day in ("2026-08-03", "2026-08-10", "2026-08-17"):        # Mondays
        make_order(f"{day}T10:00", net=100, units=2)
    make_order("2026-08-04T10:00", net=700, units=1)              # a Tuesday
    _, weekdays = analytics.day_of_week(*AUG)

    monday, tuesday = weekdays[0], weekdays[1]
    assert monday.net_sales_pence == 300
    assert monday.payment_order_count == 3
    assert monday.net_units == 6
    assert monday.average_order_value_pence == 100
    assert tuesday.net_sales_pence == 700


def test_weekday_correctly_identifies_a_sunday(analytics, make_order):
    make_order("2026-08-09T10:00", net=400)      # Sunday
    _, weekdays = analytics.day_of_week(*AUG)
    assert weekdays[6].iso_weekday == 7
    assert weekdays[6].net_sales_pence == 400


def test_refunds_reduce_weekday_revenue_without_raising_payment_count(
    analytics, make_order
):
    make_order("2026-08-03T10:00", net=1000, units=2)
    make_order("2026-08-03T11:00", net=-250, units=-1,
               event_type=OrderEventType.REFUND)
    _, weekdays = analytics.day_of_week(*AUG)

    monday = weekdays[0]
    assert monday.net_sales_pence == 750
    assert monday.payment_order_count == 1
    assert monday.net_units == 1
    assert monday.average_order_value_pence == 750


def test_weekday_totals_reconcile_with_the_overview(analytics, make_order):
    for day, net in (("2026-08-03", 100), ("2026-08-05", 250), ("2026-08-09", 375)):
        make_order(f"{day}T10:00", net=net, units=1)
    _, overview = analytics.overview(*AUG)
    _, weekdays = analytics.day_of_week(*AUG)

    assert sum(w.net_sales_pence for w in weekdays) == overview.net_sales_pence
    assert sum(w.payment_order_count for w in weekdays) == overview.payment_order_count
    assert sum(w.net_units for w in weekdays) == overview.net_units


# --- peak hours --------------------------------------------------------------


def test_grid_is_always_seven_by_twentyfour(analytics):
    _, grid = analytics.peak_hours(*AUG)
    assert len(grid.cells) == 168
    assert grid.cells[0].iso_weekday == 1 and grid.cells[0].hour == 0
    assert grid.cells[-1].iso_weekday == 7 and grid.cells[-1].hour == 23
    assert grid.peak_payment_order_count == 0
    assert grid.busiest == []


def test_cells_are_ordered_monday_midnight_to_sunday_23h(analytics):
    _, grid = analytics.peak_hours(*AUG)
    assert [(c.iso_weekday, c.hour) for c in grid.cells] == [
        (d, h) for d in range(1, 8) for h in range(24)
    ]


def test_hours_are_grouped_in_local_time_under_bst(analytics, make_order):
    """14:30 local in August is 13:30 UTC. Grouping on UTC would report 13."""
    make_order("2026-08-03T14:30", net=500)
    _, grid = analytics.peak_hours(*AUG)
    hot = [c for c in grid.cells if c.payment_order_count]
    assert len(hot) == 1
    assert (hot[0].iso_weekday, hot[0].hour) == (1, 14)


def test_hours_are_grouped_in_local_time_under_gmt(analytics, make_order):
    """In January local and UTC agree, so the same wall time gives hour 14."""
    make_order("2026-01-05T14:30", net=500)       # Monday
    _, grid = analytics.peak_hours(date(2026, 1, 1), date(2026, 1, 31))
    hot = [c for c in grid.cells if c.payment_order_count]
    assert (hot[0].iso_weekday, hot[0].hour) == (1, 14)


def test_bst_midnight_order_belongs_to_its_local_day_and_hour(analytics, make_order):
    """00:30 BST on Sat 1 Aug is 23:30 UTC on Fri 31 Jul. UTC grouping would
    file it as Friday 23:00 — wrong day AND wrong hour."""
    make_order("2026-08-01T00:30", net=500)       # Saturday
    _, grid = analytics.peak_hours(*AUG)
    hot = [c for c in grid.cells if c.payment_order_count]
    assert (hot[0].iso_weekday, hot[0].hour) == (6, 0)


def test_october_dst_transition_keeps_local_hours(analytics, make_order):
    """25 Oct 2026 is clocks-back Sunday; 26 Oct is GMT."""
    make_order("2026-10-24T23:30", net=100)       # Sat, BST
    make_order("2026-10-26T00:30", net=200)       # Mon, GMT
    _, grid = analytics.peak_hours(date(2026, 10, 1), date(2026, 10, 31))
    hot = {(c.iso_weekday, c.hour): c.net_sales_pence
           for c in grid.cells if c.payment_order_count}
    assert hot == {(6, 23): 100, (1, 0): 200}


def test_busiest_ranks_by_payment_order_volume(analytics, make_order):
    for _ in range(3):
        make_order("2026-08-03T12:00", net=100)
    for _ in range(5):
        make_order("2026-08-04T09:00", net=100)
    make_order("2026-08-05T17:00", net=100)
    _, grid = analytics.peak_hours(*AUG)

    assert grid.peak_payment_order_count == 5
    assert [(c.iso_weekday, c.hour, c.payment_order_count) for c in grid.busiest] == [
        (2, 9, 5), (1, 12, 3), (3, 17, 1),
    ]


def test_busiest_excludes_refund_only_cells(analytics, make_order):
    make_order("2026-08-03T12:00", net=-100, units=-1,
               event_type=OrderEventType.REFUND)
    _, grid = analytics.peak_hours(*AUG)
    assert grid.busiest == []
    cell = next(c for c in grid.cells if (c.iso_weekday, c.hour) == (1, 12))
    assert cell.payment_order_count == 0
    assert cell.net_sales_pence == -100      # the money still lands


def test_peak_hour_totals_reconcile_with_the_overview(analytics, make_order):
    make_order("2026-08-03T09:00", net=100, units=1)
    make_order("2026-08-05T14:00", net=250, units=3)
    make_order("2026-08-09T20:00", net=-50, units=-1,
               event_type=OrderEventType.REFUND)
    _, overview = analytics.overview(*AUG)
    _, grid = analytics.peak_hours(*AUG)

    assert sum(c.net_sales_pence for c in grid.cells) == overview.net_sales_pence
    assert sum(c.payment_order_count for c in grid.cells) == overview.payment_order_count
    assert sum(c.net_units for c in grid.cells) == overview.net_units


# --- channel mix -------------------------------------------------------------


def test_channels_stay_distinct_and_are_never_merged(analytics, make_order):
    for channel in (Channel.IN_STORE, Channel.DELIVERY, Channel.COLLECTION,
                    Channel.ONLINE, Channel.MIXED, Channel.UNKNOWN):
        make_order("2026-08-03T10:00", net=100, channel=channel)
    _, shares = analytics.channel_mix(*AUG)
    assert {s.totals.channel for s in shares} == {
        Channel.IN_STORE, Channel.DELIVERY, Channel.COLLECTION,
        Channel.ONLINE, Channel.MIXED, Channel.UNKNOWN,
    }
    assert len(shares) == 6


def test_channels_are_ordered_by_net_sales_descending(analytics, make_order):
    make_order("2026-08-03T10:00", net=100, channel=Channel.ONLINE)
    make_order("2026-08-03T11:00", net=900, channel=Channel.IN_STORE)
    make_order("2026-08-03T12:00", net=500, channel=Channel.DELIVERY)
    _, shares = analytics.channel_mix(*AUG)
    assert [s.totals.channel for s in shares] == [
        Channel.IN_STORE, Channel.DELIVERY, Channel.ONLINE
    ]


def test_channel_percentages_sum_to_one_hundred(analytics, make_order):
    make_order("2026-08-03T10:00", net=250, channel=Channel.IN_STORE)
    make_order("2026-08-03T11:00", net=250, channel=Channel.IN_STORE)
    make_order("2026-08-03T12:00", net=500, channel=Channel.DELIVERY)
    _, shares = analytics.channel_mix(*AUG)

    by_channel = {s.totals.channel: s for s in shares}
    assert by_channel[Channel.IN_STORE].share_of_net_sales_percent == 50.0
    assert by_channel[Channel.DELIVERY].share_of_net_sales_percent == 50.0
    assert by_channel[Channel.IN_STORE].share_of_payment_orders_percent == pytest.approx(66.67)
    assert sum(s.share_of_net_sales_percent for s in shares) == 100.0
    assert sum(s.share_of_payment_orders_percent for s in shares) == pytest.approx(100.0, abs=0.01)


def test_zero_totals_give_null_shares_not_a_division_error(analytics, make_order):
    """A refund-only period: no paid orders, and net sales is not positive."""
    make_order("2026-08-03T10:00", net=-100, units=-1,
               event_type=OrderEventType.REFUND, channel=Channel.IN_STORE)
    _, shares = analytics.channel_mix(*AUG)

    assert len(shares) == 1
    assert shares[0].totals.net_sales_pence == -100
    assert shares[0].share_of_payment_orders_percent is None
    assert shares[0].share_of_net_sales_percent is None
    assert shares[0].totals.average_order_value_pence == 0


def test_empty_period_returns_no_channels(analytics):
    _, shares = analytics.channel_mix(*AUG)
    assert shares == []


def test_refunds_reduce_channel_revenue_without_raising_payment_count(
    analytics, make_order
):
    make_order("2026-08-03T10:00", net=1000, units=2, channel=Channel.DELIVERY)
    make_order("2026-08-03T11:00", net=-400, units=-1,
               event_type=OrderEventType.REFUND, channel=Channel.DELIVERY)
    make_order("2026-08-03T12:00", net=600, units=1, channel=Channel.IN_STORE)
    _, shares = analytics.channel_mix(*AUG)

    delivery = next(s for s in shares if s.totals.channel is Channel.DELIVERY)
    assert delivery.totals.net_sales_pence == 600
    assert delivery.totals.payment_order_count == 1
    assert delivery.totals.net_units == 1
    assert delivery.share_of_payment_orders_percent == 50.0


def test_channel_totals_reconcile_with_the_overview(analytics, make_order):
    make_order("2026-08-03T10:00", net=1000, units=2, channel=Channel.IN_STORE)
    make_order("2026-08-04T10:00", net=500, units=1, channel=Channel.DELIVERY)
    make_order("2026-08-05T10:00", net=-100, units=-1,
               event_type=OrderEventType.REFUND, channel=Channel.ONLINE)
    _, overview = analytics.overview(*AUG)
    _, shares = analytics.channel_mix(*AUG)

    assert sum(s.totals.net_sales_pence for s in shares) == overview.net_sales_pence
    assert sum(s.totals.payment_order_count for s in shares) == overview.payment_order_count
    assert sum(s.totals.net_units for s in shares) == overview.net_units
