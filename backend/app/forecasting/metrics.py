"""Forecast accuracy measures.

Two, deliberately. MAE says how wrong a typical day is in the unit the business
thinks in; WAPE expresses the same total error as a share of the trade that
actually happened, which is what makes different targets and different periods
comparable.

MAPE is absent on purpose. It divides by each day's actual, so one closed day
makes it undefined and one very quiet day makes it enormous — and a café has
both. A metric that a single Christmas Day can dominate is not a metric.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ForecastMetrics:
    """Accuracy over a set of (actual, forecast) pairs."""

    count: int
    #: Mean absolute error, in the target's own unit (pence for money).
    mae: float | None
    #: sum|actual - forecast| / sum|actual|, as a percentage.
    #: None when the denominator is zero — see `wape`.
    wape_percent: float | None
    #: Retained so folds can be pooled without re-reading the observations.
    absolute_error_total: float
    absolute_actual_total: float

    @property
    def mae_pounds(self) -> float | None:
        """MAE read as pounds. Presentation only — never persisted as money."""
        return None if self.mae is None else self.mae / 100.0


def mean_absolute_error(
    actuals: Sequence[float], forecasts: Sequence[float]
) -> float | None:
    """None for an empty set: no observations is not an error of zero."""
    _check_aligned(actuals, forecasts)
    if not actuals:
        return None
    return sum(abs(a - f) for a, f in zip(actuals, forecasts)) / len(actuals)


def wape(actuals: Sequence[float], forecasts: Sequence[float]) -> float | None:
    """Weighted absolute percentage error:

        sum(abs(actual - forecast)) / sum(abs(actual))    x 100

    Returns None when `sum(abs(actual))` is zero — a stretch in which nothing
    traded. The error is real and MAE still reports it; expressing it as a
    percentage of nothing is undefined, and inventing 0% or 100% would both be
    lies. Absolute values in the denominator so a refund-dominated day
    contributes its magnitude instead of cancelling a positive day out.
    """
    _check_aligned(actuals, forecasts)
    denominator = sum(abs(a) for a in actuals)
    if denominator == 0:
        return None
    numerator = sum(abs(a - f) for a, f in zip(actuals, forecasts))
    return numerator / denominator * 100.0


def evaluate(
    actuals: Sequence[float], forecasts: Sequence[float]
) -> ForecastMetrics:
    _check_aligned(actuals, forecasts)
    return ForecastMetrics(
        count=len(actuals),
        mae=mean_absolute_error(actuals, forecasts),
        wape_percent=wape(actuals, forecasts),
        absolute_error_total=sum(abs(a - f) for a, f in zip(actuals, forecasts)),
        absolute_actual_total=sum(abs(a) for a in actuals),
    )


def pool(parts: Sequence[ForecastMetrics]) -> ForecastMetrics:
    """Combine per-fold metrics into one figure over every forecast day.

    Pooled from the raw totals, NOT averaged from the per-fold rates. Averaging
    WAPEs would weight a quiet fortnight as heavily as a busy one and quietly
    change what the number means.
    """
    count = sum(p.count for p in parts)
    error_total = sum(p.absolute_error_total for p in parts)
    actual_total = sum(p.absolute_actual_total for p in parts)

    return ForecastMetrics(
        count=count,
        mae=(error_total / count) if count else None,
        wape_percent=(error_total / actual_total * 100.0) if actual_total else None,
        absolute_error_total=error_total,
        absolute_actual_total=actual_total,
    )


def _check_aligned(actuals: Sequence[float], forecasts: Sequence[float]) -> None:
    if len(actuals) != len(forecasts):
        raise ValueError(
            f"actuals and forecasts must align: {len(actuals)} vs {len(forecasts)}"
        )
