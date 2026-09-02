"""Analytics endpoints.

Handlers stay thin: validate input, delegate to the analytics service, shape the
response. No SQL and no date arithmetic here.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.analytics.service import AnalyticsService
from app.analytics.windows import InvalidDateRange
from app.api.deps import get_analytics_service
from app.schemas.analytics import (
    OverviewResponse,
    RevenueBucketResponse,
    RevenueResponse,
)
from app.schemas.imports import ErrorResponse

router = APIRouter(prefix="/analytics", tags=["analytics"])

_DATE_HELP = (
    "Inclusive local calendar date (Europe/London), not UTC. The final day is "
    "included in full."
)

BAD_RANGE = {400: {"model": ErrorResponse, "description": "Invalid date range"}}


def _window_or_400(call):
    try:
        return call()
    except InvalidDateRange as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"detail": str(exc), "code": "invalid_date_range"},
        ) from exc


@router.get(
    "/overview",
    response_model=OverviewResponse,
    summary="Headline KPIs for a date range",
    description=(
        "Net sales, gross sales, discounts, order counts and average order "
        "value for an inclusive local date range.\n\n"
        "Financial totals include refunds as negative amounts; the order count "
        "counts payments only, so a refund reduces revenue without inflating "
        "volume."
    ),
    responses=BAD_RANGE,
)
def overview(
    start_date: date = Query(..., description=_DATE_HELP),
    end_date: date = Query(..., description=_DATE_HELP),
    service: AnalyticsService = Depends(get_analytics_service),
) -> OverviewResponse:
    window, totals = _window_or_400(lambda: service.overview(start_date, end_date))
    return OverviewResponse(
        start_date=window.start_date,
        end_date=window.end_date,
        net_sales_pence=totals.net_sales_pence,
        gross_sales_pence=totals.gross_sales_pence,
        discounts_pence=totals.discounts_pence,
        payment_order_count=totals.payment_order_count,
        refund_event_count=totals.refund_event_count,
        net_units=totals.net_units,
        average_order_value_pence=totals.average_order_value_pence,
    )


@router.get(
    "/revenue",
    response_model=RevenueResponse,
    summary="Revenue over time",
    description=(
        "An ordered time series bucketed by local trading day or ISO week "
        "(Monday-start). Periods with no trade are returned as explicit zero "
        "buckets so a closed day is visible rather than missing."
    ),
    responses=BAD_RANGE,
)
def revenue(
    start_date: date = Query(..., description=_DATE_HELP),
    end_date: date = Query(..., description=_DATE_HELP),
    granularity: Literal["day", "week"] = Query(
        "day", description="Bucket size. Weekly buckets start on Monday."
    ),
    service: AnalyticsService = Depends(get_analytics_service),
) -> RevenueResponse:
    series = _window_or_400(
        lambda: service.revenue(start_date, end_date, granularity)
    )
    return RevenueResponse(
        start_date=series.window.start_date,
        end_date=series.window.end_date,
        granularity=series.granularity,
        buckets=[
            RevenueBucketResponse(
                period_start=b.period_start,
                net_sales_pence=b.net_sales_pence,
                gross_sales_pence=b.gross_sales_pence,
                discounts_pence=b.discounts_pence,
                payment_order_count=b.payment_order_count,
                net_units=b.net_units,
            )
            for b in series.buckets
        ],
    )
