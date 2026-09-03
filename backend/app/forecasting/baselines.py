"""Transparent forecasting baselines.

These are not strawmen. A café's trade is dominated by day of week, and
"the same as last week" is what an experienced operator actually predicts. A
model that cannot beat these has learned nothing worth deploying, and saying so
before building one is the whole point of this commit.

LEAKAGE SAFETY IS STRUCTURAL, NOT A CONVENTION.
Every baseline receives only `history` — the observations strictly BEFORE the
forecast origin — and a horizon. It is not given the actuals it is predicting,
so it cannot consult them by accident. A future baseline that needs more
context must be handed it explicitly, which makes the leakage question visible
in the signature rather than buried in the implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

#: Trade repeats weekly, so every baseline here is keyed to a 7-day cycle.
WEEK = 7


class Baseline(ABC):
    """A univariate forecaster over a contiguous daily history."""

    #: Shown in reports.
    name: str
    #: Fewest history points the method needs to produce a defined forecast.
    min_history: int

    @abstractmethod
    def forecast(self, history: Sequence[float], horizon: int) -> list[float]:
        """`horizon` values for the days immediately following `history`."""

    def _check(self, history: Sequence[float], horizon: int) -> None:
        if horizon < 1:
            raise ValueError(f"horizon must be at least 1, got {horizon}")
        if len(history) < self.min_history:
            raise ValueError(
                f"{self.name} needs at least {self.min_history} days of history, "
                f"got {len(history)}"
            )


class SeasonalNaive(Baseline):
    """forecast(t) = actual(t - 7).

    The baseline to beat. It carries the weekday effect exactly and costs
    nothing, so any model's improvement over it is the honest measure of what
    the model added.

    Beyond seven days ahead the value at t-7 is itself unobserved, so the last
    complete observed week is recycled — the standard seasonal-naive extension,
    and the reason a 14-day horizon reuses each weekday's last actual twice.
    """

    name = "seasonal_naive"
    min_history = WEEK

    def forecast(self, history: Sequence[float], horizon: int) -> list[float]:
        self._check(history, horizon)
        last_week = history[-WEEK:]
        return [float(last_week[step % WEEK]) for step in range(horizon)]


class SameWeekdayMean(Baseline):
    """Mean of the previous N occurrences of the same weekday.

    Smoother than seasonal-naive: one unusual Saturday moves the forecast by a
    quarter rather than wholly. That is usually an advantage and occasionally
    not — a step change in trade takes four weeks to be fully absorbed — which
    is exactly the trade-off the backtest is there to settle.

    Only whole same-weekday observations from `history` are used, so the
    windows never reach across the forecast origin.
    """

    def __init__(self, occurrences: int = 4) -> None:
        if occurrences < 1:
            raise ValueError("occurrences must be at least 1")
        self.occurrences = occurrences
        self.name = f"same_weekday_mean_{occurrences}"
        self.min_history = WEEK * occurrences

    def forecast(self, history: Sequence[float], horizon: int) -> list[float]:
        self._check(history, horizon)

        forecasts: list[float] = []
        for step in range(horizon):
            # The most recent history point sharing this step's weekday. The
            # history is contiguous and ends the day before the origin, so
            # weekday alignment is pure arithmetic — no date handling needed,
            # and no way to be off by a day at a BST boundary.
            latest = len(history) - WEEK + (step % WEEK)
            window = [
                history[latest - WEEK * back]
                for back in range(self.occurrences)
                if latest - WEEK * back >= 0
            ]
            forecasts.append(sum(float(v) for v in window) / len(window))
        return forecasts


class DriftFreeMean(Baseline):
    """Mean of the trailing 28 days, ignoring weekday entirely.

    Included as a control, not a contender. If a weekday-aware baseline cannot
    beat a flat average, the weekly cycle is weaker than assumed and the whole
    modelling approach needs rethinking — so it is worth knowing.
    """

    name = "trailing_mean_28"
    min_history = 28

    def forecast(self, history: Sequence[float], horizon: int) -> list[float]:
        self._check(history, horizon)
        window = history[-28:]
        mean = sum(float(v) for v in window) / len(window)
        return [mean] * horizon


def default_baselines() -> list[Baseline]:
    """The set every backtest reports, in the order they are presented."""
    return [SeasonalNaive(), SameWeekdayMean(4), DriftFreeMean()]
