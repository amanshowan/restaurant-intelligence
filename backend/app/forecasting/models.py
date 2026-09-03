"""Predictive models, evaluated under the Commit 21 harness.

Two candidates, both modest by design. With ~365 observations the question is
not which architecture is most powerful but whether *any* learned model beats a
four-week same-weekday mean by enough to justify its existence.

RECURSIVE MULTI-STEP FORECASTING
We forecast 14 days, not one. Day 8's `lag_7` points at day 1 — which is inside
the horizon and therefore unknown at forecast time. It must use the model's own
day-1 PREDICTION, never the actual. Reading the actual would produce a backtest
score no live forecast could reproduce, and it is the single easiest way to
fake a good result. `recursive_forecast` is the only path that produces a
multi-step forecast, so the rule cannot be bypassed by a caller.

TARGET-SPECIFIC OUTPUT SEMANTICS
Counts are floored at zero; money is not. See `FLOOR_AT_ZERO`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.forecasting.features import (
    DEFAULT_FEATURES,
    MIN_HISTORY,
    NUMERIC_INDICES,
    FeatureConfig,
    binary_indices,
    build_design_matrix,
    row_for_next_day,
)
from app.forecasting.series import DailyObservation, Target

#: Whether a target's forecast may go below zero.
#:
#: A count cannot: "-3 payment orders" is not a quantity anyone can act on, and
#: presenting it would discredit the whole forecast. Flooring is applied to the
#: EMITTED forecast — the actuals and the errors they produce are untouched.
#:
#: Net sales is NOT floored. A day whose refunds outweigh its sales genuinely
#: has negative net sales; the series contains such days by construction, and
#: clamping the forecast would make the model structurally unable to predict
#: the one kind of day a manager most wants warning of.
FLOOR_AT_ZERO: dict[Target, bool] = {
    "net_sales_pence": False,
    "payment_order_count": True,
    "net_units": True,
}

#: Small, conservative, and fixed in advance. Selected per fold by inner
#: validation confined to the training window — never against the outer test.
ALPHA_GRID: tuple[float, ...] = (0.1, 1.0, 10.0, 100.0)

#: Inner validation blocks carved off the END of the training window, each one
#: scored with the same recursive multi-step procedure as the outer folds.
DEFAULT_INNER_FOLDS = 3


def _apply_floor(value: float, target: Target) -> float:
    return max(value, 0.0) if FLOOR_AT_ZERO[target] else value


def recursive_forecast(
    predict: Callable[[np.ndarray], float],
    history: Sequence[float],
    last_day,
    horizon: int,
    target: Target,
    config: FeatureConfig = DEFAULT_FEATURES,
) -> list[float]:
    """Forecast `horizon` days, feeding each prediction back as history.

    `history` is the observed past only. After each step the PREDICTION is
    appended, so a lag reaching into the horizon reads a prediction. Actual
    future values are not a parameter of this function and cannot be consulted.
    """
    from datetime import timedelta

    working = [float(v) for v in history]
    forecasts: list[float] = []

    for step in range(1, horizon + 1):
        day = last_day + timedelta(days=step)
        prediction = _apply_floor(
            float(predict(row_for_next_day(working, day, config))), target
        )
        forecasts.append(prediction)
        # The model's own output becomes tomorrow's history. This is the line
        # that makes day 8 use the day-1 prediction rather than the day-1 truth.
        working.append(prediction)

    return forecasts


def _ridge_pipeline(alpha: float, config: FeatureConfig = DEFAULT_FEATURES) -> Pipeline:
    """Scaling for the numeric columns; the calendar dummies pass through.

    Ridge penalises coefficients on their own scale, so lag features measured
    in pence must be standardised or the penalty falls almost entirely on them.
    The weekday dummies are already 0/1: standardising them would rescale by
    their frequency and penalise a rare weekday differently from a common one,
    for no benefit.

    The scaler lives INSIDE the pipeline, so `fit` computes its mean and
    variance from the training rows of that fold alone. Scaling once over the
    whole year would leak the test period's level into every fold.
    """
    return Pipeline(
        [
            (
                "prepare",
                ColumnTransformer(
                    [
                        ("scale", StandardScaler(), list(NUMERIC_INDICES)),
                        ("keep", "passthrough", list(binary_indices(config))),
                    ]
                ),
            ),
            ("ridge", Ridge(alpha=alpha)),
        ]
    )


def select_alpha(
    train: Sequence[DailyObservation],
    target: Target,
    *,
    horizon: int,
    alphas: Sequence[float] = ALPHA_GRID,
    inner_folds: int = DEFAULT_INNER_FOLDS,
    config: FeatureConfig = DEFAULT_FEATURES,
) -> float:
    """Choose `alpha` using only the training window.

    The last `inner_folds x horizon` training days are held out as inner
    validation blocks and scored with the same recursive multi-step forecast
    the outer harness uses, so the criterion matches the objective. The outer
    test block is not a parameter here and cannot be reached.
    """
    usable = [
        cut
        for cut in (len(train) - k * horizon for k in range(inner_folds, 0, -1))
        if cut > MIN_HISTORY + horizon
    ]
    if not usable:
        # Too little history to validate honestly. Prefer the stronger penalty
        # rather than guessing — a short window is exactly when overfitting
        # bites hardest.
        return max(alphas)

    scores: list[tuple[float, float]] = []
    for alpha in alphas:
        errors: list[float] = []
        for cut in usable:
            inner_train = train[:cut]
            inner_test = train[cut : cut + horizon]
            design = build_design_matrix(inner_train, target, config)
            model = _ridge_pipeline(alpha, config).fit(design.X, design.y)

            predicted = recursive_forecast(
                lambda row: model.predict(row.reshape(1, -1))[0],
                [float(o.value(target)) for o in inner_train],
                inner_train[-1].day,
                len(inner_test),
                target,
                config,
            )
            errors.extend(
                abs(float(o.value(target)) - p)
                for o, p in zip(inner_test, predicted)
            )
        scores.append((float(np.mean(errors)), alpha))

    # Ties resolve to the LARGER alpha: with this little data, prefer the more
    # regularised model when the evidence cannot separate them.
    best = min(scores, key=lambda s: (s[0], -s[1]))
    return best[1]


@dataclass
class RidgeForecaster:
    """Ridge on calendar and lag features, with per-fold alpha selection."""

    horizon: int = 14
    alphas: Sequence[float] = ALPHA_GRID
    inner_folds: int = DEFAULT_INNER_FOLDS
    features: FeatureConfig = DEFAULT_FEATURES
    name: str = "ridge"
    min_history: int = MIN_HISTORY + 14
    #: Diagnostic only: which alpha each call selected, for the report.
    selected_alphas: list[float] = field(default_factory=list)

    def forecast_from(
        self, train: Sequence[DailyObservation], target: Target, horizon: int
    ) -> list[float]:
        alpha = select_alpha(
            train,
            target,
            horizon=horizon,
            alphas=self.alphas,
            inner_folds=self.inner_folds,
            config=self.features,
        )
        self.selected_alphas.append(alpha)

        design = build_design_matrix(train, target, self.features)
        model = _ridge_pipeline(alpha, self.features).fit(design.X, design.y)

        return recursive_forecast(
            lambda row: model.predict(row.reshape(1, -1))[0],
            [float(o.value(target)) for o in train],
            train[-1].day,
            horizon,
            target,
            self.features,
        )


@dataclass
class GradientBoostingForecaster:
    """HistGradientBoostingRegressor — the nonlinear challenger.

    Hyperparameters are fixed and conservative rather than searched. On ~200
    training rows a large search would select noise, and the point of the
    challenger is to answer one question: does a nonlinearity buy anything a
    linear model cannot? A shallow, heavily-regularised booster answers it.
    """

    horizon: int = 14
    features: FeatureConfig = DEFAULT_FEATURES
    name: str = "gradient_boosting"
    min_history: int = MIN_HISTORY + 14
    random_state: int = 0

    def _model(self) -> HistGradientBoostingRegressor:
        return HistGradientBoostingRegressor(
            max_depth=3,
            max_iter=200,
            learning_rate=0.05,
            min_samples_leaf=10,
            l2_regularization=1.0,
            early_stopping=False,
            # Fixed seed: a forecast that changes between identical runs cannot
            # be audited.
            random_state=self.random_state,
        )

    def forecast_from(
        self, train: Sequence[DailyObservation], target: Target, horizon: int
    ) -> list[float]:
        design = build_design_matrix(train, target, self.features)
        model = self._model().fit(design.X, design.y)

        return recursive_forecast(
            lambda row: model.predict(row.reshape(1, -1))[0],
            [float(o.value(target)) for o in train],
            train[-1].day,
            horizon,
            target,
            self.features,
        )
