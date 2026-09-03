"""The canonical daily forecasting series.

Every assertion uses synthetic data. The real café figures belong in the
read-only annual analysis, never in a unit test — a test that hardcodes them
starts failing the day another month is imported, for no reason connected to
the code it covers.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.forecasting.series import (
    DailyObservation,
    SeriesIntegrityError,
    build_daily_series,
    validate_series,
    values,
)


# --- local-day bucketing -----------------------------------------------------


def test_series_covers_every_calendar_day_in_the_range(session_factory, make_order):
    make_order("2026-06-01T12:00", net=1000)
    make_order("2026-06-03T12:00", net=2000)

    series = build_daily_series(session_factory, date(2026, 6, 1), date(2026, 6, 5))

    assert [o.day for o in series] == [date(2026, 6, d) for d in range(1, 6)]


def test_days_with_no_trade_are_explicit_zeros_not_gaps(session_factory, make_order):
    """A closure is a fact about the business, not missing data.

    Compacting it away would shift every lag: 'last Tuesday' would silently
    become 'the Tuesday before that' for the rest of the series.
    """
    make_order("2026-06-01T12:00", net=1000, units=2)

    series = build_daily_series(session_factory, date(2026, 6, 1), date(2026, 6, 3))

    assert len(series) == 3
    assert series[1].day == date(2026, 6, 2)
    assert series[1].net_sales_pence == 0
    assert series[1].payment_order_count == 0
    assert series[1].net_units == 0
    assert series[1].traded is False
    assert series[0].traded is True


def test_bucketing_uses_europe_london_not_utc(session_factory, make_order):
    """00:30 on a BST morning is 23:30 UTC the day before.

    Grouping on UTC would file it under the previous trading day — the single
    most common way a 'daily sales' series is quietly wrong for seven months of
    the year.
    """
    make_order("2026-06-15T00:30", net=500)

    series = build_daily_series(session_factory, date(2026, 6, 14), date(2026, 6, 15))
    by_day = {o.day: o for o in series}

    assert by_day[date(2026, 6, 15)].net_sales_pence == 500
    assert by_day[date(2026, 6, 14)].net_sales_pence == 0


def test_bucketing_is_correct_either_side_of_the_bst_transition(
    session_factory, make_order
):
    """Clocks go forward on 29 March 2026 and back on 25 October 2026.

    The same wall-clock time is a different UTC instant either side, and both
    must still land on the day the till recorded.
    """
    make_order("2026-03-28T23:30", net=100)   # GMT, before the change
    make_order("2026-03-30T00:30", net=200)   # BST, after it
    make_order("2026-10-26T00:30", net=300)   # GMT again, after clocks go back

    spring = {o.day: o for o in build_daily_series(
        session_factory, date(2026, 3, 28), date(2026, 3, 30))}
    autumn = {o.day: o for o in build_daily_series(
        session_factory, date(2026, 10, 25), date(2026, 10, 26))}

    assert spring[date(2026, 3, 28)].net_sales_pence == 100
    assert spring[date(2026, 3, 29)].net_sales_pence == 0
    assert spring[date(2026, 3, 30)].net_sales_pence == 200
    assert autumn[date(2026, 10, 26)].net_sales_pence == 300


def test_march_29_2026_has_23_hours_but_is_still_one_row(session_factory, make_order):
    """The day the clocks go forward is 23 hours long. It is still one day."""
    make_order("2026-03-29T03:00", net=400)

    series = build_daily_series(session_factory, date(2026, 3, 29), date(2026, 3, 29))

    assert len(series) == 1
    assert series[0].net_sales_pence == 400


# --- analytics semantics carried through -------------------------------------


def test_refunds_reduce_net_sales_and_units_but_not_order_count(
    session_factory, make_order
):
    """Identical to /analytics/overview, because it is the same SQL."""
    from app.models.enums import OrderEventType

    make_order("2026-06-01T10:00", net=1000, units=3)
    make_order("2026-06-01T11:00", net=-400, units=-1,
               event_type=OrderEventType.REFUND)

    series = build_daily_series(session_factory, date(2026, 6, 1), date(2026, 6, 1))

    assert series[0].net_sales_pence == 600
    assert series[0].net_units == 2
    assert series[0].payment_order_count == 1     # the refund is not an order


def test_a_day_whose_refunds_outweigh_sales_is_kept_negative(
    session_factory, make_order
):
    """Clamping a negative day to zero would hide the days a forecast most
    needs to explain."""
    from app.models.enums import OrderEventType

    make_order("2026-06-01T10:00", net=500, units=1)
    make_order("2026-06-01T11:00", net=-900, units=-2,
               event_type=OrderEventType.REFUND)

    series = build_daily_series(session_factory, date(2026, 6, 1), date(2026, 6, 1))

    assert series[0].net_sales_pence == -400
    assert series[0].net_units == -1
    assert series[0].traded is True


# --- integrity ---------------------------------------------------------------


def observations(start: date, count: int, **fields) -> list[DailyObservation]:
    from datetime import timedelta
    return [
        DailyObservation(day=start + timedelta(days=i), **fields) for i in range(count)
    ]


def test_validate_accepts_a_well_formed_series():
    validate_series(observations(date(2026, 1, 1), 10))


def test_validate_rejects_a_calendar_gap():
    series = [
        DailyObservation(day=date(2026, 1, 1)),
        DailyObservation(day=date(2026, 1, 4)),
    ]
    with pytest.raises(SeriesIntegrityError, match="gap"):
        validate_series(series)


def test_validate_rejects_out_of_order_days():
    series = [
        DailyObservation(day=date(2026, 1, 2)),
        DailyObservation(day=date(2026, 1, 1)),
    ]
    with pytest.raises(SeriesIntegrityError, match="chronological"):
        validate_series(series)


def test_validate_rejects_duplicate_days():
    series = [
        DailyObservation(day=date(2026, 1, 1)),
        DailyObservation(day=date(2026, 1, 1)),
    ]
    with pytest.raises(SeriesIntegrityError, match="duplicate"):
        validate_series(series)


def test_validate_rejects_a_negative_order_count():
    series = [DailyObservation(day=date(2026, 1, 1), payment_order_count=-1)]
    with pytest.raises(SeriesIntegrityError, match="cannot be negative"):
        validate_series(series)


def test_validate_permits_negative_money_and_units():
    """A refund-heavy day is legitimate; only a COUNT cannot be negative."""
    validate_series(
        [DailyObservation(date(2026, 1, 1), net_sales_pence=-500, net_units=-2)]
    )


def test_validate_rejects_a_non_integer_target():
    series = [DailyObservation(day=date(2026, 1, 1), net_sales_pence=12.5)]  # type: ignore[arg-type]
    with pytest.raises(SeriesIntegrityError, match="whole number"):
        validate_series(series)


def test_validate_enforces_a_minimum_length():
    with pytest.raises(SeriesIntegrityError, match="at least 30"):
        validate_series(observations(date(2026, 1, 1), 10), minimum_days=30)


def test_validate_rejects_an_empty_series():
    with pytest.raises(SeriesIntegrityError):
        validate_series([])


def test_values_extracts_a_target_in_order():
    series = [
        DailyObservation(date(2026, 1, 1), net_sales_pence=10),
        DailyObservation(date(2026, 1, 2), net_sales_pence=20),
    ]
    assert values(series, "net_sales_pence") == [10, 20]
