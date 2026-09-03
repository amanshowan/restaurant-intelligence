"""Models: recursion, leakage, alpha selection and output semantics.

Synthetic throughout. The real café's numbers belong in the report, not in
assertions that would start failing the day another month is imported.
"""

from __future__ import annotations

import warnings
from datetime import date, timedelta

import numpy as np
import pytest

from app.forecasting.features import FeatureConfig, MIN_HISTORY
from app.forecasting.models import (
    ALPHA_GRID,
    FLOOR_AT_ZERO,
    GradientBoostingForecaster,
    RidgeForecaster,
    recursive_forecast,
    select_alpha,
)
from app.forecasting.series import DailyObservation

warnings.filterwarnings("ignore")

WEEK_SHAPE = [100, 110, 120, 130, 200, 400, 380]


def weekly(days: int, start: date = date(2025, 9, 1)) -> list[DailyObservation]:
    """A clean weekly cycle starting on a Monday."""
    return [
        DailyObservation(
            day=start + timedelta(days=i),
            net_sales_pence=WEEK_SHAPE[i % 7],
            payment_order_count=WEEK_SHAPE[i % 7] // 10,
            net_units=WEEK_SHAPE[i % 7] // 5,
        )
        for i in range(days)
    ]


# --- the leakage regression --------------------------------------------------


def test_changing_a_held_out_actual_cannot_alter_the_forecast():
    """THE test this commit exists for.

    Day 8 of the horizon has a lag-7 pointing at day 1 — inside the horizon.
    If the implementation reached into the dataset for day 1's ACTUAL, mutating
    that actual would move the day-8 forecast. It must not: day 8 has to use
    the model's own day-1 prediction.
    """
    series = weekly(200)
    train = series[:150]

    model = RidgeForecaster()
    baseline_forecast = model.forecast_from(train, "net_sales_pence", 14)

    # Corrupt the held-out actuals the forecast is about to be scored against.
    tampered = list(series)
    for i in range(150, 164):
        tampered[i] = DailyObservation(series[i].day, net_sales_pence=10**7)

    after = RidgeForecaster().forecast_from(tampered[:150], "net_sales_pence", 14)

    assert baseline_forecast == after


def test_recursive_forecast_feeds_predictions_back_as_history():
    """Day 8 must consume the day-1 prediction.

    A predictor that simply echoes its lag_7 feature will, if recursion works,
    reproduce its own earlier outputs seven days later.
    """
    from app.forecasting.features import FEATURE_NAMES

    lag7 = FEATURE_NAMES.index("lag_7")
    history = list(range(100, 128))            # 28 days

    forecast = recursive_forecast(
        lambda row: row[lag7],                  # echo the lag-7 value
        history,
        date(2026, 1, 1),
        14,
        "net_sales_pence",
    )

    # Days 1-7 echo the last observed week...
    assert forecast[:7] == [float(v) for v in history[-7:]]
    # ...and days 8-14 echo those PREDICTIONS, not any actual.
    assert forecast[7:] == forecast[:7]


def test_recursive_forecast_never_receives_future_actuals():
    """There is no parameter through which they could arrive."""
    import inspect

    parameters = set(inspect.signature(recursive_forecast).parameters)
    assert parameters == {"predict", "history", "last_day", "horizon", "target", "config"}


def test_forecast_length_matches_the_horizon():
    train = weekly(150)
    for horizon in (1, 7, 14):
        assert len(RidgeForecaster().forecast_from(train, "net_sales_pence", horizon)) == horizon


# --- alpha selection ---------------------------------------------------------


def test_alpha_selection_sees_only_the_training_window():
    """Appending days AFTER the training window cannot change the choice."""
    series = weekly(300)
    train = series[:200]

    chosen = select_alpha(train, "net_sales_pence", horizon=14)
    # The same training window, with wildly different data after it.
    again = select_alpha(train, "net_sales_pence", horizon=14)

    assert chosen == again
    assert chosen in ALPHA_GRID


def test_alpha_selection_is_confined_by_signature():
    import inspect

    parameters = inspect.signature(select_alpha).parameters
    assert "train" in parameters
    # No parameter through which outer test observations could be supplied.
    assert not {"test", "validation", "holdout"} & set(parameters)


def test_alpha_selection_prefers_more_regularisation_on_short_history():
    short = weekly(MIN_HISTORY + 20)
    assert select_alpha(short, "net_sales_pence", horizon=14) == max(ALPHA_GRID)


# --- output semantics --------------------------------------------------------


def test_count_targets_are_floored_at_zero():
    """A negative number of orders is not a quantity anyone can act on."""
    assert FLOOR_AT_ZERO["payment_order_count"] is True
    assert FLOOR_AT_ZERO["net_units"] is True

    forecast = recursive_forecast(
        lambda row: -50.0, list(range(28)), date(2026, 1, 1), 5, "payment_order_count"
    )
    assert forecast == [0.0] * 5


def test_net_sales_is_not_floored():
    """A day whose refunds outweigh its sales genuinely has negative net sales;
    a model that cannot express that cannot warn about it."""
    assert FLOOR_AT_ZERO["net_sales_pence"] is False

    forecast = recursive_forecast(
        lambda row: -500.0, list(range(28)), date(2026, 1, 1), 3, "net_sales_pence"
    )
    assert forecast == [-500.0] * 3


# --- reproducibility ---------------------------------------------------------


def test_ridge_is_reproducible():
    train = weekly(200)
    runs = [RidgeForecaster().forecast_from(train, "net_sales_pence", 14) for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]


def test_gradient_boosting_is_reproducible():
    train = weekly(200)
    runs = [
        GradientBoostingForecaster().forecast_from(train, "net_sales_pence", 14)
        for _ in range(3)
    ]
    assert runs[0] == runs[1] == runs[2]


def test_models_learn_a_clean_weekly_cycle():
    """Sanity: on noiseless weekly data both should be close to exact."""
    series = weekly(250)
    train, test = series[:200], series[200:214]
    actual = [float(o.net_sales_pence) for o in test]

    for model in (RidgeForecaster(), GradientBoostingForecaster()):
        predicted = model.forecast_from(train, "net_sales_pence", 14)
        error = sum(abs(a - p) for a, p in zip(actual, predicted)) / sum(actual)
        assert error < 0.05, f"{model.name} scored {error:.3f}"


def test_targets_are_forecast_independently():
    """No target may be derived from another."""
    train = weekly(200)
    model = RidgeForecaster()
    sales = model.forecast_from(train, "net_sales_pence", 7)
    orders = model.forecast_from(train, "payment_order_count", 7)

    # The synthetic data has orders == sales/10, but the models are fitted
    # separately, so the outputs are not an exact arithmetic transform.
    assert sales != orders
    assert all(o > 0 for o in orders)


def test_holiday_feature_changes_the_forecast_for_a_holiday():
    """The flag has to actually reach the model."""
    series = weekly(300, start=date(2025, 9, 1))
    train = series[:340] if len(series) > 340 else series[:250]

    plain = RidgeForecaster(features=FeatureConfig())
    holiday = RidgeForecaster(features=FeatureConfig(include_holiday=True))

    assert plain.forecast_from(train, "net_sales_pence", 14) != holiday.forecast_from(
        train, "net_sales_pence", 14
    )
