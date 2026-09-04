"""Producing a forecast for the days after the last observation.

PRODUCTION METHOD
Ridge on calendar and lag features, with the fixed-date holiday flag. Chosen
because rolling-origin backtesting showed it reduces pooled error on all three
targets against the strongest Commit 21 baseline, and because the improvement
survives excluding the festive fortnight — so it is not merely patching
Christmas. The margin is modest and honestly reported: see
`historical_wape_percent` on every response, which is the model's measured
error on 238 unseen days, not a claim about the future.

The service deliberately returns NO prediction intervals. Producing one would
mean validating its coverage, which this commit has not done, and an
unvalidated interval is worse than none — it invites the reader to trust a
range that has never been checked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.forecasting.backtest import (
    DEFAULT_HORIZON,
    DEFAULT_MIN_TRAIN_DAYS,
    run_backtest,
)
from app.forecasting.features import FeatureConfig
from app.forecasting.metrics import ForecastMetrics
from app.forecasting.models import FLOOR_AT_ZERO, RidgeForecaster
from app.forecasting.series import (
    DailyObservation,
    SeriesIntegrityError,
    Target,
    build_daily_series,
)

#: Longest horizon this service will produce. Beyond a fortnight the recursive
#: forecast is predicting almost entirely from its own output, and nothing in
#: the backtest supports it.
MAX_HORIZON_DAYS = 14

#: The production feature set: base features plus the fixed-date holiday flag.
PRODUCTION_FEATURES = FeatureConfig(include_holiday=True)
PRODUCTION_METHOD = "ridge_holiday"

#: How much history the service asks the database for. A year gives the model
#: every weekday roughly 52 times and keeps the request bounded.
TRAINING_WINDOW_DAYS = 365

#: What each target is counted in, so a caller never has to guess whether a
#: number is pence or a quantity.
TARGET_UNITS: dict[Target, str] = {
    "net_sales_pence": "pence",
    "payment_order_count": "orders",
    "net_units": "units",
}


@dataclass(frozen=True)
class ForecastPoint:
    day: date
    #: Integer at the boundary: pence stay pence, counts stay whole.
    predicted_value: int


@dataclass(frozen=True)
class Forecast:
    target: Target
    unit: str
    method: str
    #: Last day of REAL observed data the model saw. Everything after this is
    #: prediction.
    trained_through: date
    forecast_start: date
    forecast_end: date
    horizon_days: int
    points: list[ForecastPoint]
    #: Measured on unseen days by the rolling-origin backtest — the honest
    #: statement of how wrong this method has historically been. None when the
    #: evaluated period contained no trade at all.
    historical_wape_percent: float | None
    historical_mae: float | None
    backtest_folds: int
    backtest_horizon_days: int


class InsufficientHistoryError(SeriesIntegrityError):
    """Not enough observed history to forecast responsibly."""


def _to_integer(value: float, target: Target) -> int:
    """Round to the target's natural unit.

    Money is integer pence at the boundary — a fractional penny is not a
    quantity the rest of the system can carry. Counts are whole by definition.
    The zero floor was already applied inside the model for count targets; this
    repeats it only so rounding cannot push -0.4 to a negative integer.
    """
    rounded = int(round(value))
    return max(rounded, 0) if FLOOR_AT_ZERO[target] else rounded


class ForecastService:
    """Forecasts the next 1-14 days from the latest observation.

    One request performs one coherent operation: the series is read once, the
    model is fitted once, and all `horizon_days` points come from a single
    recursive pass. Nothing is refitted per point.

    Backtest metrics are memoised per process, keyed on the data they describe,
    so quoting historical accuracy does not re-run a ten-second evaluation on
    every request. This is a cache, not a model registry — persistence is
    deliberately out of scope for this commit.
    """

    def __init__(self, session_factory, *, today: date | None = None) -> None:
        self._session_factory = session_factory
        self._today = today
        self._metric_cache: dict[tuple[date, int, Target], ForecastMetrics] = {}

    def forecast(self, target: Target, horizon_days: int) -> Forecast:
        if not 1 <= horizon_days <= MAX_HORIZON_DAYS:
            raise ValueError(
                f"horizon_days must be between 1 and {MAX_HORIZON_DAYS}, "
                f"got {horizon_days}"
            )

        series = self._load_series()
        last_day = series[-1].day

        forecaster = RidgeForecaster(features=PRODUCTION_FEATURES)
        predicted = forecaster.forecast_from(series, target, horizon_days)

        points = [
            ForecastPoint(
                day=last_day.fromordinal(last_day.toordinal() + step),
                predicted_value=_to_integer(value, target),
            )
            for step, value in enumerate(predicted, start=1)
        ]

        metrics = self._historical_metrics(series, target)

        return Forecast(
            target=target,
            unit=TARGET_UNITS[target],
            method=PRODUCTION_METHOD,
            trained_through=last_day,
            forecast_start=points[0].day,
            forecast_end=points[-1].day,
            horizon_days=horizon_days,
            points=points,
            historical_wape_percent=metrics.wape_percent,
            historical_mae=metrics.mae,
            backtest_folds=self._fold_count,
            backtest_horizon_days=DEFAULT_HORIZON,
        )

    # -- internals ------------------------------------------------------------

    _fold_count: int = 0

    def _load_series(self) -> list[DailyObservation]:
        """The most recent `TRAINING_WINDOW_DAYS` of observations.

        Bounded at BOTH ends by data that exists:

        * the window ends on the latest day the database holds, not on the wall
          clock — forecasting past the data would treat unimported days as
          closures;
        * it starts no earlier than the FIRST observed day. Zero-filling back
          before trading began would manufacture months of fake closures and
          teach the model that the business is usually shut.
        """
        first, latest = self.observed_range()
        if first is None or latest is None:
            raise InsufficientHistoryError(
                "no orders have been imported, so there is nothing to forecast from"
            )

        window_start = latest.fromordinal(
            latest.toordinal() - (TRAINING_WINDOW_DAYS - 1)
        )
        start = max(window_start, first)
        series = build_daily_series(self._session_factory, start, latest)

        required = DEFAULT_MIN_TRAIN_DAYS + DEFAULT_HORIZON
        if len(series) < required:
            raise InsufficientHistoryError(
                f"{len(series)} day(s) of history is not enough to forecast; "
                f"at least {required} are required"
            )
        return series

    def observed_range(self) -> tuple[date | None, date | None]:
        """First and last LOCAL day the database holds an order for.

        Public because it is the canonical answer to "how far does the data
        go", which the M7 question layer needs in order to resolve "last
        month" against the data rather than against the wall clock. Exposing
        the accessor that already existed is preferable to a second query
        computing the same thing somewhere else.
        """
        from sqlalchemy import func, select

        from app.config import settings
        from app.models import Order

        local_day = func.date(
            func.timezone(settings.business_timezone, Order.occurred_at)
        )
        with self._session_factory() as session:
            row = session.execute(
                select(func.min(local_day), func.max(local_day))
            ).one()
        return row[0], row[1]

    def _historical_metrics(
        self, series: list[DailyObservation], target: Target
    ) -> ForecastMetrics:
        key = (series[-1].day, len(series), target)
        if key not in self._metric_cache:
            report = run_backtest(
                series,
                [RidgeForecaster(features=PRODUCTION_FEATURES)],
                targets=(target,),
            )
            self._fold_count = report.fold_count
            self._metric_cache[key] = report.evaluations[0].overall
        return self._metric_cache[key]
