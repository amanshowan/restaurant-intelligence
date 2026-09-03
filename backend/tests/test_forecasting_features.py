"""Feature construction: the layer where leakage would originate."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from app.forecasting.features import (
    DEFAULT_FEATURES,
    FEATURE_NAMES,
    MIN_HISTORY,
    FeatureConfig,
    binary_indices,
    build_design_matrix,
    feature_names,
    future_days,
    is_fixed_holiday,
    row_for_next_day,
)
from app.forecasting.series import DailyObservation


def ramp(n: int, start: date = date(2025, 9, 1)) -> list[DailyObservation]:
    """value == index, so every lag is checkable by eye."""
    return [
        DailyObservation(day=start + timedelta(days=i), net_sales_pence=i)
        for i in range(n)
    ]


def index_of(name: str) -> int:
    return FEATURE_NAMES.index(name)


# --- lags --------------------------------------------------------------------


def test_lags_read_exactly_seven_fourteen_twentyone_and_twentyeight_days_back():
    history = list(range(100))            # history[-1] == 99 is "yesterday"
    row = row_for_next_day(history, date(2026, 1, 1))

    assert row[index_of("lag_7")] == 93   # history[-7]
    assert row[index_of("lag_14")] == 86
    assert row[index_of("lag_21")] == 79
    assert row[index_of("lag_28")] == 72


def test_rolling_means_use_only_trailing_windows():
    history = [0.0] * 21 + [10.0] * 7     # last 7 are 10, last 28 average 2.5
    row = row_for_next_day(history, date(2026, 1, 1))

    assert row[index_of("trailing_mean_7")] == pytest.approx(10.0)
    assert row[index_of("trailing_mean_28")] == pytest.approx(2.5)


def test_a_row_never_contains_the_day_it_describes():
    """The structural guarantee: `row_for_next_day` is not given the value it
    is used to predict, so it cannot encode it."""
    history = list(range(50))
    row = row_for_next_day(history, date(2026, 1, 1))

    assert 50 not in row                  # the day being predicted
    assert max(row[len(binary_indices()):]) <= 49


def test_row_requires_enough_history():
    with pytest.raises(ValueError, match="at least 28"):
        row_for_next_day(list(range(27)), date(2026, 1, 1))


# --- calendar encoding -------------------------------------------------------


def test_weekday_is_one_hot_with_monday_as_the_reference_level():
    history = list(range(40))
    monday = row_for_next_day(history, date(2026, 1, 5))     # a Monday
    sunday = row_for_next_day(history, date(2026, 1, 11))    # a Sunday

    assert list(monday[:6]) == [0, 0, 0, 0, 0, 0]            # reference
    assert list(sunday[:6]) == [0, 0, 0, 0, 0, 1]
    assert sum(sunday[:6]) == 1


def test_every_weekday_gets_a_distinct_encoding():
    history = list(range(40))
    encodings = {
        tuple(row_for_next_day(history, date(2026, 1, 5) + timedelta(days=d))[:6])
        for d in range(7)
    }
    assert len(encodings) == 7


def test_binary_columns_are_identified_for_the_preprocessor():
    """The scaler must skip them; that depends on these indices being right."""
    for index in binary_indices(DEFAULT_FEATURES):
        assert FEATURE_NAMES[index].startswith("weekday_")


# --- optional feature blocks -------------------------------------------------


def test_holiday_flag_is_purely_calendar_derived():
    """Fixed dates only. It cannot be inferred from whether a day took £0,
    which would be leakage from the target."""
    assert is_fixed_holiday(date(2025, 12, 25))
    assert is_fixed_holiday(date(2026, 12, 26))
    assert is_fixed_holiday(date(2026, 1, 1))
    assert not is_fixed_holiday(date(2026, 1, 2))
    assert not is_fixed_holiday(date(2026, 7, 24))


def test_holiday_flag_appends_one_binary_column():
    config = FeatureConfig(include_holiday=True)
    history = list(range(40))

    assert feature_names(config)[-1] == "is_fixed_holiday"
    assert row_for_next_day(history, date(2026, 1, 1), config)[-1] == 1.0
    assert row_for_next_day(history, date(2026, 1, 2), config)[-1] == 0.0
    assert len(binary_indices(config)) == len(binary_indices()) + 1


def test_month_dummies_are_off_by_default():
    assert "month_2" not in feature_names()
    assert "month_2" in feature_names(FeatureConfig(include_month=True))


# --- design matrix -----------------------------------------------------------


def test_design_matrix_skips_the_days_that_lack_history():
    observations = ramp(40)
    design = build_design_matrix(observations, "net_sales_pence")

    assert len(design) == 40 - MIN_HISTORY
    assert design.days[0] == observations[MIN_HISTORY].day


def test_design_matrix_targets_match_their_days():
    design = build_design_matrix(ramp(40), "net_sales_pence")
    assert design.y[0] == MIN_HISTORY            # value == index
    assert design.X.shape == (40 - MIN_HISTORY, len(FEATURE_NAMES))


def test_design_matrix_rows_use_only_earlier_observations():
    """Change a LATER observation; earlier rows must be byte-identical."""
    observations = ramp(60)
    before = build_design_matrix(observations, "net_sales_pence")

    tampered = list(observations)
    tampered[50] = DailyObservation(observations[50].day, net_sales_pence=999_999)
    after = build_design_matrix(tampered, "net_sales_pence")

    # Rows describing days before index 50 cannot have moved.
    boundary = 50 - MIN_HISTORY
    assert np.array_equal(before.X[:boundary], after.X[:boundary])
    assert np.array_equal(before.y[:boundary], after.y[:boundary])


def test_design_matrix_needs_more_than_the_minimum_history():
    with pytest.raises(ValueError, match="more than 28"):
        build_design_matrix(ramp(28), "net_sales_pence")


def test_future_days_follow_the_last_observation():
    assert future_days(date(2026, 8, 31), 3) == [
        date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)
    ]


def test_future_days_rejects_a_non_positive_horizon():
    with pytest.raises(ValueError, match="at least 1"):
        future_days(date(2026, 8, 31), 0)
