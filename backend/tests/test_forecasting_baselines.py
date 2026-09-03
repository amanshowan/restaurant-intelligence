"""Baselines, metrics and leakage-safe fold generation.

All synthetic and fully deterministic: every expected number below is worked
out by hand in the test, so a failure says what changed rather than that two
implementations disagree.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.forecasting.backtest import (
    DEFAULT_HORIZON,
    BacktestFold,
    generate_folds,
    run_backtest,
)
from app.forecasting.baselines import (
    DriftFreeMean,
    SameWeekdayMean,
    SeasonalNaive,
    default_baselines,
)
from app.forecasting.metrics import evaluate, mean_absolute_error, pool, wape
from app.forecasting.series import DailyObservation, SeriesIntegrityError


# --- seasonal naive ----------------------------------------------------------


def test_seasonal_naive_repeats_the_previous_week():
    history = [10, 20, 30, 40, 50, 60, 70]

    assert SeasonalNaive().forecast(history, 7) == [10, 20, 30, 40, 50, 60, 70]


def test_seasonal_naive_uses_only_the_last_seven_days():
    history = [999] * 7 + [10, 20, 30, 40, 50, 60, 70]

    assert SeasonalNaive().forecast(history, 3) == [10, 20, 30]


def test_seasonal_naive_recycles_the_week_beyond_seven_days():
    """Day 8's t-7 is itself unobserved, so the last complete week repeats."""
    history = [10, 20, 30, 40, 50, 60, 70]

    forecast = SeasonalNaive().forecast(history, DEFAULT_HORIZON)

    assert len(forecast) == 14
    assert forecast[:7] == [10, 20, 30, 40, 50, 60, 70]
    assert forecast[7:] == [10, 20, 30, 40, 50, 60, 70]


def test_seasonal_naive_needs_a_full_week():
    with pytest.raises(ValueError, match="at least 7 days"):
        SeasonalNaive().forecast([1, 2, 3], 7)


# --- same-weekday mean -------------------------------------------------------


def test_same_weekday_mean_averages_the_matching_weekdays():
    """Four weeks; each weekday holds 1, 2, 3, 4 in successive weeks, so every
    weekday's mean is 2.5 whatever the day."""
    history = [w for w in (1, 2, 3, 4) for _ in range(7)]

    forecast = SameWeekdayMean(4).forecast(history, 7)

    assert forecast == [2.5] * 7


def test_same_weekday_mean_is_weekday_specific():
    # Monday=100, Tuesday=200 ... in every week; four identical weeks.
    week = [100, 200, 300, 400, 500, 600, 700]
    history = week * 4

    forecast = SameWeekdayMean(4).forecast(history, 7)

    assert forecast == [100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0]


def test_same_weekday_mean_uses_only_the_requested_occurrences():
    """A fifth week back must not be consulted."""
    week_old = [0] * 7
    history = week_old + [100] * 7 + [100] * 7 + [100] * 7 + [100] * 7

    assert SameWeekdayMean(4).forecast(history, 1)[0] == 100.0


def test_same_weekday_mean_needs_four_whole_weeks():
    with pytest.raises(ValueError, match="at least 28 days"):
        SameWeekdayMean(4).forecast([1] * 27, 7)


def test_same_weekday_mean_occurrences_must_be_positive():
    with pytest.raises(ValueError, match="at least 1"):
        SameWeekdayMean(0)


def test_trailing_mean_ignores_weekday():
    history = [0] * 14 + [10] * 14      # last 28 days average 5
    assert DriftFreeMean().forecast(history, 3) == [5.0, 5.0, 5.0]


# --- leakage -----------------------------------------------------------------


def test_baselines_cannot_see_beyond_the_history_they_are_given():
    """The structural guarantee: a baseline receives history and a horizon, and
    nothing else. Changing the future cannot change the forecast."""
    history = [10, 20, 30, 40, 50, 60, 70] * 4

    for baseline in default_baselines():
        first = baseline.forecast(list(history), DEFAULT_HORIZON)
        second = baseline.forecast(list(history), DEFAULT_HORIZON)
        assert first == second           # deterministic
        # A baseline given a longer history that only differs AFTER the origin
        # cannot be constructed — there is no parameter to pass it through.
        assert len(first) == DEFAULT_HORIZON


def test_forecasts_are_reproducible_across_runs():
    history = [float(i % 7) * 11 for i in range(120)]
    runs = [
        [b.forecast(history, DEFAULT_HORIZON) for b in default_baselines()]
        for _ in range(3)
    ]
    assert runs[0] == runs[1] == runs[2]


# --- metrics -----------------------------------------------------------------


def test_mae_is_the_mean_absolute_error():
    assert mean_absolute_error([10, 20], [12, 17]) == pytest.approx(2.5)


def test_mae_of_an_empty_set_is_undefined_not_zero():
    assert mean_absolute_error([], []) is None


def test_wape_is_total_error_over_total_actual():
    # |10-12| + |20-17| = 5 ; |10| + |20| = 30
    assert wape([10, 20], [12, 17]) == pytest.approx(5 / 30 * 100)


def test_wape_is_undefined_when_nothing_traded():
    """Zero denominator. The error is real and MAE still reports it, but a
    percentage of nothing is undefined — 0% and 100% would both be lies."""
    assert wape([0, 0], [50, 50]) is None
    assert mean_absolute_error([0, 0], [50, 50]) == 50


def test_wape_uses_absolute_actuals_so_refund_days_do_not_cancel():
    """+100 and -100 sum to zero but represent 200 of trade."""
    assert wape([100, -100], [100, -100]) == pytest.approx(0.0)
    assert wape([100, -100], [0, 0]) == pytest.approx(100.0)


def test_metrics_require_aligned_inputs():
    with pytest.raises(ValueError, match="align"):
        evaluate([1, 2, 3], [1, 2])


def test_pooling_weights_by_day_not_by_fold():
    """A quiet fortnight must not count as much as a busy one."""
    busy = evaluate([1000] * 14, [900] * 14)      # 1400 error over 14000
    quiet = evaluate([10] * 14, [9] * 14)         # 14 error over 140

    combined = pool([busy, quiet])

    assert combined.count == 28
    assert combined.absolute_error_total == pytest.approx(1414)
    assert combined.wape_percent == pytest.approx(1414 / 14140 * 100)


# --- folds -------------------------------------------------------------------


def test_folds_are_non_overlapping_and_cover_distinct_days():
    folds = generate_folds(100, horizon=14, min_train_days=30)

    tested = [
        day
        for fold in folds
        for day in range(fold.test_start, fold.test_start + fold.horizon)
    ]
    assert len(tested) == len(set(tested))       # every day scored once


def test_every_complete_fold_has_exactly_fourteen_forecast_points():
    folds = generate_folds(365, horizon=14, min_train_days=120)

    assert folds
    assert all(f.horizon == 14 for f in folds)
    # A partial final window is never emitted.
    assert all(f.test_start + f.horizon <= 365 for f in folds)


def test_first_fold_starts_after_the_minimum_training_history():
    folds = generate_folds(200, horizon=14, min_train_days=60)

    assert folds[0].train_end_exclusive == 60
    assert folds[0].test_start == 60


def test_training_never_includes_the_test_window():
    """The property the whole harness exists to guarantee."""
    for fold in generate_folds(365, horizon=14, min_train_days=120):
        assert fold.train_end_exclusive <= fold.test_start


def test_later_folds_may_reuse_earlier_observations():
    """A real forecaster accumulates history; that is not leakage."""
    folds = generate_folds(200, horizon=14, min_train_days=60)
    assert folds[1].train_days > folds[0].train_days


def test_fold_generation_is_deterministic():
    assert generate_folds(365) == generate_folds(365)


def test_no_folds_when_history_is_too_short():
    assert generate_folds(50, horizon=14, min_train_days=120) == []


def test_fold_arguments_are_validated():
    with pytest.raises(ValueError, match="horizon"):
        generate_folds(100, horizon=0)
    with pytest.raises(ValueError, match="min_train_days"):
        generate_folds(100, min_train_days=0)
    with pytest.raises(ValueError, match="step"):
        generate_folds(100, step=0)


def test_fold_slices_the_series_it_describes():
    series = [DailyObservation(date(2026, 1, 1) + timedelta(days=i)) for i in range(50)]
    fold = BacktestFold(index=0, train_end_exclusive=30, test_start=30, horizon=14)

    assert len(fold.train(series)) == 30
    assert len(fold.test(series)) == 14
    assert fold.test(series)[0].day == series[30].day


# --- end-to-end backtest -----------------------------------------------------


def synthetic_year(days: int = 365) -> list[DailyObservation]:
    """A clean weekly cycle: weekends busier, no noise, no trend."""
    start = date(2025, 9, 1)                      # a Monday
    weekday_sales = [100, 110, 120, 130, 200, 400, 380]
    return [
        DailyObservation(
            day=start + timedelta(days=i),
            net_sales_pence=weekday_sales[i % 7],
            payment_order_count=weekday_sales[i % 7] // 10,
            net_units=weekday_sales[i % 7] // 5,
        )
        for i in range(days)
    ]


def test_backtest_scores_a_perfectly_periodic_series_exactly():
    """With a pure weekly cycle both weekday-aware baselines are perfect and
    the weekday-blind control is not — which is the sanity check that the
    harness is wired up correctly."""
    report = run_backtest(synthetic_year(), default_baselines())

    assert report.fold_count == 17
    assert report.horizon == 14

    by_name = {
        e.baseline: e for e in report.for_target("net_sales_pence")
    }
    assert by_name["seasonal_naive"].overall.wape_percent == pytest.approx(0.0)
    assert by_name["same_weekday_mean_4"].overall.wape_percent == pytest.approx(0.0)
    assert by_name["trailing_mean_28"].overall.wape_percent > 10


def test_backtest_reports_every_target_for_every_baseline():
    report = run_backtest(synthetic_year(), default_baselines())

    assert len(report.evaluations) == 3 * 3
    assert {e.target for e in report.evaluations} == {
        "net_sales_pence", "payment_order_count", "net_units"
    }


def test_backtest_pools_exactly_the_days_it_forecast():
    report = run_backtest(synthetic_year(), [SeasonalNaive()])
    evaluation = report.for_target("net_sales_pence")[0]

    assert evaluation.overall.count == report.fold_count * report.horizon
    assert all(f.metrics.count == 14 for f in evaluation.folds)


def test_backtest_rejects_a_history_too_short_for_the_schedule():
    with pytest.raises(SeriesIntegrityError, match="cannot support a backtest"):
        run_backtest(synthetic_year(60), default_baselines())


def test_backtest_rejects_a_baseline_needing_more_history_than_the_first_fold():
    with pytest.raises(SeriesIntegrityError, match="needs 28 days"):
        run_backtest(synthetic_year(120), [DriftFreeMean()], min_train_days=20)


def test_backtest_is_reproducible():
    first = run_backtest(synthetic_year(), default_baselines())
    second = run_backtest(synthetic_year(), default_baselines())

    assert [
        (e.baseline, e.target, e.overall.mae, e.overall.wape_percent)
        for e in first.evaluations
    ] == [
        (e.baseline, e.target, e.overall.mae, e.overall.wape_percent)
        for e in second.evaluations
    ]


def test_backtest_handles_a_closed_stretch_without_dividing_by_zero():
    """Two weeks of closure inside the evaluated window: WAPE for that fold is
    undefined, and that must not crash or silently become a number."""
    series = synthetic_year()
    for i in range(120, 134):
        series[i] = DailyObservation(day=series[i].day)      # all zeros

    report = run_backtest(series, [SeasonalNaive()])
    closed = report.for_target("net_sales_pence")[0].folds[0]

    assert closed.metrics.wape_percent is None
    assert closed.metrics.mae is not None and closed.metrics.mae > 0
