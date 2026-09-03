"""Response schemas for the forecast endpoint.

A forecast is a prediction, and the schema is written so a consumer cannot
mistake it for a record of fact: every response carries the method that
produced it, the last day of REAL data behind it, and the error that method
actually made on unseen history.
"""

from __future__ import annotations

# Aliased: the point schema has a field literally called `date`, which would
# otherwise shadow the type in that class body and leave the annotation
# unresolvable.
from datetime import date as DateType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: The external names, mapping onto the internal targets.
ForecastTarget = Literal["net_sales", "payment_orders", "net_units"]

PENCE = "Integer minor units (pence). Never a float."


class ForecastPointResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: DateType = Field(description="Local calendar day being predicted.")
    predicted_value: int = Field(
        description=(
            "The prediction, in the response's `unit`. Integer: pence for "
            "money, whole counts otherwise."
        )
    )


class ForecastResponse(BaseModel):
    """A short-horizon forecast, with the evidence for trusting it."""

    model_config = ConfigDict(frozen=True)

    target: ForecastTarget
    unit: Literal["pence", "orders", "units"] = Field(
        description="What `predicted_value` counts, so it is never ambiguous."
    )
    method: str = Field(
        description=(
            "The forecasting method used. Reported so a stored forecast can be "
            "attributed after the method changes."
        )
    )

    trained_through: DateType = Field(
        description=(
            "Last day of OBSERVED data behind this forecast. Everything from "
            "`forecast_start` onward is predicted, not recorded."
        )
    )
    forecast_start: DateType
    forecast_end: DateType
    horizon_days: int = Field(ge=1, le=14)

    points: list[ForecastPointResponse] = Field(
        description="Chronological, one per day, exactly `horizon_days` long."
    )

    historical_wape_percent: float | None = Field(
        default=None,
        description=(
            "How wrong this method was on days it had never seen, measured by "
            "rolling-origin backtest: sum|actual - forecast| / sum|actual|. "
            "Null when the evaluated period contained no trade. This is "
            "measured error, NOT a confidence interval for these predictions."
        ),
    )
    historical_mae: float | None = Field(
        default=None,
        description="Mean absolute error over the same backtest, in `unit`.",
    )
    backtest_folds: int = Field(
        description="Independent forecast origins the metrics were pooled over."
    )
    backtest_horizon_days: int = Field(
        description="Horizon each backtest fold forecast, in days."
    )
