"""Forecast endpoint.

Thin, like the other analytics routes: validate, delegate, shape. No model
code here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_forecast_service
from app.api.imports import UNPROCESSABLE
from app.forecasting.series import SeriesIntegrityError, Target
from app.forecasting.service import MAX_HORIZON_DAYS, ForecastService
from app.schemas.forecast import (
    ForecastPointResponse,
    ForecastResponse,
    ForecastTarget,
)
from app.schemas.imports import ErrorResponse

router = APIRouter(prefix="/analytics", tags=["analytics"])

#: External name -> internal target. The external names read as business
#: measures; the internal ones carry their unit in the name.
_TARGETS: dict[ForecastTarget, Target] = {
    "net_sales": "net_sales_pence",
    "payment_orders": "payment_order_count",
    "net_units": "net_units",
}


@router.get(
    "/forecast",
    response_model=ForecastResponse,
    summary="Short-horizon daily forecast",
    description=(
        "Predicts the next 1-14 local trading days from the most recent "
        "imported day.\n\n"
        "These are PREDICTIONS, not records. Every response carries the method "
        "that produced it, the last day of real data behind it, and "
        "`historical_wape_percent` — the error that method actually made on "
        "unseen days under rolling-origin backtesting. No prediction intervals "
        "are returned: producing one would mean validating its coverage, which "
        "has not been done, and an unvalidated interval invites false "
        "confidence.\n\n"
        "Counts are floored at zero because a negative number of orders is not "
        "a quantity anyone can act on. Net sales is NOT floored: a day whose "
        "refunds outweigh its sales genuinely has negative net sales."
    ),
    responses={
        422: {
            "model": ErrorResponse,
            "description": "Invalid target or horizon, or too little history",
        },
    },
)
def forecast(
    target: ForecastTarget = Query(
        "net_sales", description="Which measure to forecast."
    ),
    horizon_days: int = Query(
        14,
        ge=1,
        le=MAX_HORIZON_DAYS,
        description=(
            f"Days ahead to predict, 1 to {MAX_HORIZON_DAYS}. Beyond a "
            "fortnight the forecast is predicting almost entirely from its own "
            "output and nothing in the backtest supports it."
        ),
    ),
    service: ForecastService = Depends(get_forecast_service),
) -> ForecastResponse:
    try:
        result = service.forecast(_TARGETS[target], horizon_days)
    except SeriesIntegrityError as exc:
        # Too little history, or a series that failed its integrity checks.
        # Neither is the caller's fault, but both are theirs to act on.
        raise HTTPException(
            UNPROCESSABLE,
            detail={"detail": str(exc), "code": "insufficient_history"},
        ) from exc

    return ForecastResponse(
        target=target,
        unit=result.unit,
        method=result.method,
        trained_through=result.trained_through,
        forecast_start=result.forecast_start,
        forecast_end=result.forecast_end,
        horizon_days=result.horizon_days,
        points=[
            ForecastPointResponse(date=p.day, predicted_value=p.predicted_value)
            for p in result.points
        ],
        historical_wape_percent=result.historical_wape_percent,
        historical_mae=result.historical_mae,
        backtest_folds=result.backtest_folds,
        backtest_horizon_days=result.backtest_horizon_days,
    )
