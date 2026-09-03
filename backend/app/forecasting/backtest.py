"""Rolling-origin (walk-forward) backtesting.

A random train/test split is meaningless for a time series: it trains on next
Tuesday to predict last Tuesday, and reports an accuracy the business can never
experience. Every fold here trains only on the past and is scored only on the
future, which is the situation a live forecast is actually in.

    |<-------- train ------->|<- test ->|
    |<----------- train ---------->|<- test ->|
    |<--------------- train -------------->|<- test ->|

Earlier observations are reused by later folds — that is correct, a real
forecaster accumulates history. Later observations are never used by earlier
folds, which is the property that must never break.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from typing import Protocol, runtime_checkable

from app.forecasting.baselines import Baseline  # noqa: F401  (re-exported)
from app.forecasting.metrics import ForecastMetrics, evaluate, pool
from app.forecasting.series import (
    DailyObservation,
    SeriesIntegrityError,
    TARGETS,
    Target,
    values,
)

#: Two weeks. Long enough to cover ordering, rota and prep decisions; short
#: enough that a daily model is still credible at the far end.
DEFAULT_HORIZON = 14

#: History required before the first origin. Four months leaves the 28-day
#: baselines a full window plus room for the weekly cycle to be established,
#: while still placing every fold in the later two-thirds of a 12-month year.
DEFAULT_MIN_TRAIN_DAYS = 120


@runtime_checkable
class Forecaster(Protocol):
    """Anything the harness can evaluate.

    Receives the TRAINING observations and a horizon, and returns that many
    values. It is never given the observations it is being scored against, so
    leakage is prevented by the signature rather than by discipline. Both the
    Commit 21 baselines and the Commit 22 models satisfy this.
    """

    name: str
    #: Fewest training days the method needs.
    min_history: int

    def forecast_from(
        self, train: Sequence[DailyObservation], target: Target, horizon: int
    ) -> list[float]: ...


@dataclass(frozen=True)
class BacktestFold:
    """One train/test split, identified by position in the series."""

    index: int
    #: Test days are series[test_start : test_start + horizon].
    train_end_exclusive: int
    test_start: int
    horizon: int

    @property
    def train_days(self) -> int:
        return self.train_end_exclusive

    def train(self, series: Sequence[DailyObservation]) -> list[DailyObservation]:
        return list(series[: self.train_end_exclusive])

    def test(self, series: Sequence[DailyObservation]) -> list[DailyObservation]:
        return list(series[self.test_start : self.test_start + self.horizon])


def generate_folds(
    series_length: int,
    *,
    horizon: int = DEFAULT_HORIZON,
    min_train_days: int = DEFAULT_MIN_TRAIN_DAYS,
    step: int | None = None,
) -> list[BacktestFold]:
    """Deterministic fold schedule for a series of `series_length` days.

    `step` defaults to `horizon`, giving NON-OVERLAPPING test windows: every
    evaluated day is scored exactly once, so pooled metrics are a plain average
    over distinct days rather than a weighted one over days counted twice.

    Takes a length rather than the series itself, so the schedule can be tested
    without constructing observations.
    """
    if horizon < 1:
        raise ValueError(f"horizon must be at least 1, got {horizon}")
    if min_train_days < 1:
        raise ValueError(f"min_train_days must be at least 1, got {min_train_days}")
    stride = horizon if step is None else step
    if stride < 1:
        raise ValueError(f"step must be at least 1, got {stride}")

    folds: list[BacktestFold] = []
    origin = min_train_days
    while origin + horizon <= series_length:
        folds.append(
            BacktestFold(
                index=len(folds),
                train_end_exclusive=origin,
                test_start=origin,
                horizon=horizon,
            )
        )
        origin += stride
    return folds


@dataclass(frozen=True)
class FoldResult:
    fold: BacktestFold
    first_test_day: date
    last_test_day: date
    metrics: ForecastMetrics


@dataclass(frozen=True)
class BaselineEvaluation:
    """One forecaster's performance on one target, across every fold.

    Named for the baselines it was written for in Commit 21; it now carries
    model results too, because they are evaluated identically.
    """

    baseline: str
    target: Target
    overall: ForecastMetrics
    folds: list[FoldResult] = field(default_factory=list)


@dataclass(frozen=True)
class BacktestReport:
    horizon: int
    min_train_days: int
    fold_count: int
    first_test_day: date | None
    last_test_day: date | None
    evaluations: list[BaselineEvaluation]

    def for_target(self, target: Target) -> list[BaselineEvaluation]:
        """Evaluations for one target, most accurate (lowest WAPE) first."""
        rows = [e for e in self.evaluations if e.target == target]
        return sorted(
            rows,
            key=lambda e: (
                e.overall.wape_percent
                if e.overall.wape_percent is not None
                else float("inf")
            ),
        )


def run_backtest(
    series: Sequence[DailyObservation],
    forecasters: Sequence[Forecaster],
    *,
    horizon: int = DEFAULT_HORIZON,
    min_train_days: int = DEFAULT_MIN_TRAIN_DAYS,
    targets: Sequence[Target] = TARGETS,
    step: int | None = None,
) -> BacktestReport:
    """Walk every fold, score every baseline on every target."""
    folds = generate_folds(
        len(series), horizon=horizon, min_train_days=min_train_days, step=step
    )
    if not folds:
        raise SeriesIntegrityError(
            f"{len(series)} day(s) of history cannot support a backtest needing "
            f"{min_train_days} training days plus a {horizon}-day horizon; "
            f"at least {min_train_days + horizon} are required"
        )

    for forecaster in forecasters:
        if min_train_days < forecaster.min_history:
            raise SeriesIntegrityError(
                f"{forecaster.name} needs {forecaster.min_history} days of history "
                f"but the first fold trains on only {min_train_days}"
            )

    evaluations: list[BaselineEvaluation] = []

    for forecaster in forecasters:
        for target in targets:
            fold_results: list[FoldResult] = []

            for fold in folds:
                train = fold.train(series)
                test = fold.test(series)

                # The forecaster sees the TRAINING observations only. The
                # actuals it is scored against are never passed in.
                predicted = forecaster.forecast_from(train, target, fold.horizon)
                actual = [float(v) for v in values(test, target)]

                fold_results.append(
                    FoldResult(
                        fold=fold,
                        first_test_day=test[0].day,
                        last_test_day=test[-1].day,
                        metrics=evaluate(actual, predicted),
                    )
                )

            evaluations.append(
                BaselineEvaluation(
                    baseline=forecaster.name,
                    target=target,
                    overall=pool([r.metrics for r in fold_results]),
                    folds=fold_results,
                )
            )

    return BacktestReport(
        horizon=horizon,
        min_train_days=min_train_days,
        fold_count=len(folds),
        first_test_day=series[folds[0].test_start].day,
        last_test_day=series[folds[-1].test_start + horizon - 1].day,
        evaluations=evaluations,
    )
