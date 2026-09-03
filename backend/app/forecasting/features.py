"""Feature construction for the daily forecasting models.

THE LEAKAGE RULE, ONCE, HERE.
Every feature for day *t* is computed from values strictly BEFORE *t*. The
functions below take a `history` sequence and produce the row for the day that
follows it — they are never handed the day they describe, so a feature cannot
accidentally read its own target. Multi-step forecasting extends that history
with the model's own predictions (see `models.recursive_forecast`), never with
observed future actuals.

FEATURE SET, AND WHAT WAS LEFT OUT.
Roughly 365 observations, of which a fold trains on 120-344. That budget buys a
dozen features, not fifty:

  weekday one-hot (6)   the dominant signal — Sunday takes 1.57x Tuesday
  lag 7, 14, 21, 28 (4) the same weekday, one to four weeks back
  trailing 7-day mean   recent level, weekday-blind
  trailing 28-day mean  slower level, absorbs a month of drift

Deliberately excluded:

  * `same_weekday_mean_4`. It is exactly (lag7 + lag14 + lag21 + lag28) / 4 —
    an exact linear combination of features already present, so it adds a
    perfectly collinear column that a linear model cannot use. The strongest
    Commit 21 baseline IS this mean, so Ridge can reproduce it by putting 0.25
    on each lag; it simply is not given the answer pre-computed.
  * Month dummies. Eleven more columns to describe twelve months observed once
    each is memorisation, not seasonality. Quantified rather than assumed —
    see the report.
  * Any trend or index term. One year cannot separate trend from annual
    seasonality, and a linear ramp extrapolated 14 days is a liability.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from app.forecasting.series import DailyObservation, Target


@dataclass(frozen=True)
class FeatureConfig:
    """Which optional feature blocks the design matrix carries.

    Both extras default OFF. They exist so their value could be MEASURED
    rather than argued about — see the report — and so a later commit can turn
    one on with evidence instead of intuition.
    """

    #: Eleven month dummies. Twelve months observed once each.
    include_month: bool = False
    #: One flag for the fixed-date UK closures: 25 Dec, 26 Dec, 1 Jan.
    #: Purely calendar-derived and knowable years ahead, so it cannot leak —
    #: it is never inferred from whether a day happened to take £0.
    include_holiday: bool = False


DEFAULT_FEATURES = FeatureConfig()

#: Fixed-date closures. Deliberately only the three that never move: Easter and
#: the spring/summer bank holidays would need a calendar library, which is
#: scope this commit does not need.
FIXED_HOLIDAYS: frozenset[tuple[int, int]] = frozenset({(12, 25), (12, 26), (1, 1)})


def is_fixed_holiday(day: date) -> bool:
    return (day.month, day.day) in FIXED_HOLIDAYS

#: Longest lookback any feature needs. A row cannot be built without it.
MIN_HISTORY = 28

WEEK = 7
#: Monday is the reference level, so six dummies describe seven weekdays
#: without the constant collinearity a seventh would introduce.
WEEKDAY_COLUMNS = tuple(f"weekday_{d}" for d in range(1, 7))
LAG_COLUMNS = ("lag_7", "lag_14", "lag_21", "lag_28")
ROLLING_COLUMNS = ("trailing_mean_7", "trailing_mean_28")

#: Order matters: it is the column order of the design matrix, and the
#: preprocessor indexes into it.
FEATURE_NAMES: tuple[str, ...] = WEEKDAY_COLUMNS + LAG_COLUMNS + ROLLING_COLUMNS

#: Indices of the binary calendar columns. They are already 0/1 and are passed
#: through the preprocessor unscaled.
BINARY_INDICES = tuple(range(len(WEEKDAY_COLUMNS)))
NUMERIC_INDICES = tuple(range(len(WEEKDAY_COLUMNS), len(FEATURE_NAMES)))


@dataclass(frozen=True)
class DesignMatrix:
    """Rows of features with their targets and the days they describe."""

    X: np.ndarray
    y: np.ndarray
    days: list[date]

    def __len__(self) -> int:
        return len(self.days)


def feature_names(config: FeatureConfig = DEFAULT_FEATURES) -> tuple[str, ...]:
    names = list(FEATURE_NAMES)
    if config.include_month:
        names.extend(f"month_{m}" for m in range(2, 13))
    if config.include_holiday:
        names.append("is_fixed_holiday")
    return tuple(names)


def binary_indices(config: FeatureConfig = DEFAULT_FEATURES) -> tuple[int, ...]:
    """Columns that are already 0/1 and pass through the scaler untouched."""
    extra = len(feature_names(config)) - len(FEATURE_NAMES)
    return BINARY_INDICES + tuple(
        range(len(FEATURE_NAMES), len(FEATURE_NAMES) + extra)
    )


def row_for_next_day(
    history: Sequence[float], day: date, config: FeatureConfig = DEFAULT_FEATURES
) -> np.ndarray:
    """The feature row for `day`, given the values of the days before it.

    `history` must be contiguous daily values ending on `day - 1`. Nothing about
    `day` other than its position on the calendar enters the row — its value is
    what we are trying to predict and is not available here.
    """
    if len(history) < MIN_HISTORY:
        raise ValueError(
            f"need at least {MIN_HISTORY} days of history to build a feature row, "
            f"got {len(history)}"
        )

    weekday = day.weekday()  # 0 = Monday
    features: list[float] = [1.0 if weekday == d else 0.0 for d in range(1, 7)]

    # history[-1] is yesterday, so the value 7 days before `day` is history[-7].
    features.extend(float(history[-lag]) for lag in (7, 14, 21, 28))

    features.append(float(np.mean(history[-WEEK:])))
    features.append(float(np.mean(history[-MIN_HISTORY:])))

    if config.include_month:
        features.extend(1.0 if day.month == m else 0.0 for m in range(2, 13))
    if config.include_holiday:
        features.append(1.0 if is_fixed_holiday(day) else 0.0)

    return np.asarray(features, dtype=float)


def build_design_matrix(
    observations: Sequence[DailyObservation],
    target: Target,
    config: FeatureConfig = DEFAULT_FEATURES,
) -> DesignMatrix:
    """Every day in `observations` that has enough history behind it.

    The first `MIN_HISTORY` days become history only; they cannot be training
    rows because their own features would reach before the series starts.
    """
    if len(observations) <= MIN_HISTORY:
        raise ValueError(
            f"need more than {MIN_HISTORY} observations to build a design "
            f"matrix, got {len(observations)}"
        )

    values = [float(o.value(target)) for o in observations]
    rows: list[np.ndarray] = []
    targets: list[float] = []
    days: list[date] = []

    for index in range(MIN_HISTORY, len(observations)):
        # Strictly the values BEFORE this day. The slice end is exclusive, so
        # observations[index] itself is never inside its own feature window.
        rows.append(row_for_next_day(values[:index], observations[index].day, config))
        targets.append(values[index])
        days.append(observations[index].day)

    return DesignMatrix(
        X=np.vstack(rows), y=np.asarray(targets, dtype=float), days=days
    )


def future_days(last_observed: date, horizon: int) -> list[date]:
    """The `horizon` calendar days following `last_observed`."""
    if horizon < 1:
        raise ValueError(f"horizon must be at least 1, got {horizon}")
    return [last_observed + timedelta(days=step) for step in range(1, horizon + 1)]
