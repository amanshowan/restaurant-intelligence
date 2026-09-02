"""Analytics endpoints.

Handlers stay thin: validate input, delegate to the analytics service, shape the
response. No SQL and no date arithmetic here.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.analytics.service import AnalyticsService, WEEKDAY_NAMES
from app.analytics.windows import InvalidDateRange
from app.api.deps import get_analytics_service
from app.schemas.analytics import (
    ChannelMixEntry,
    ChannelMixResponse,
    DayOfWeekResponse,
    OverviewResponse,
    PeakHourCell,
    PeakHoursResponse,
    RevenueBucketResponse,
    RevenueResponse,
    WeekdayTotalsResponse,
)
from app.schemas.imports import ErrorResponse

router = APIRouter(prefix="/analytics", tags=["analytics"])

_DATE_HELP = (
    "Inclusive local calendar date (Europe/London), not UTC. The final day is "
    "included in full."
)

#: Applied to every analytics endpoint so the documented error schema matches
#: what the handlers in app/api/errors.py actually return.
BAD_RANGE = {
    400: {"model": ErrorResponse, "description": "Invalid date range"},
    422: {
        "model": ErrorResponse,
        "description": "Missing or malformed query parameter",
    },
}


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


@router.get(
    "/day-of-week",
    response_model=DayOfWeekResponse,
    summary="Trade by day of the week",
    description=(
        "Totals for each weekday, aggregated across every occurrence of that "
        "weekday in the range — all the Mondays in the period summed together, "
        "not one row per date.\n\n"
        "Always returns seven entries in Monday-to-Sunday order; a weekday with "
        "no trade is an explicit zero row."
    ),
    responses=BAD_RANGE,
)
def day_of_week(
    start_date: date = Query(..., description=_DATE_HELP),
    end_date: date = Query(..., description=_DATE_HELP),
    service: AnalyticsService = Depends(get_analytics_service),
) -> DayOfWeekResponse:
    window, weekdays = _window_or_400(
        lambda: service.day_of_week(start_date, end_date)
    )
    return DayOfWeekResponse(
        start_date=window.start_date,
        end_date=window.end_date,
        weekdays=[
            WeekdayTotalsResponse(
                iso_weekday=w.iso_weekday,
                weekday=WEEKDAY_NAMES[w.iso_weekday],
                net_sales_pence=w.net_sales_pence,
                payment_order_count=w.payment_order_count,
                net_units=w.net_units,
                average_order_value_pence=w.average_order_value_pence,
            )
            for w in weekdays
        ],
    )


@router.get(
    "/peak-hours",
    response_model=PeakHoursResponse,
    summary="Day-of-week x hour heatmap",
    description=(
        "A 7x24 grid of local trading hours, suitable for a heatmap. Hours are "
        "Europe/London, so the profile reflects when the shop was actually "
        "busy rather than a UTC-shifted approximation.\n\n"
        "Every cell is present even when empty, so the response shape is "
        "stable. `peak_payment_order_count` and `busiest` identify the "
        "highest-volume hours."
    ),
    responses=BAD_RANGE,
)
def peak_hours(
    start_date: date = Query(..., description=_DATE_HELP),
    end_date: date = Query(..., description=_DATE_HELP),
    service: AnalyticsService = Depends(get_analytics_service),
) -> PeakHoursResponse:
    window, grid = _window_or_400(lambda: service.peak_hours(start_date, end_date))
    return PeakHoursResponse(
        start_date=window.start_date,
        end_date=window.end_date,
        cells=[_cell(c) for c in grid.cells],
        peak_payment_order_count=grid.peak_payment_order_count,
        busiest=[_cell(c) for c in grid.busiest],
    )


def _cell(c) -> PeakHourCell:
    return PeakHourCell(
        iso_weekday=c.iso_weekday,
        weekday=WEEKDAY_NAMES[c.iso_weekday],
        hour=c.hour,
        payment_order_count=c.payment_order_count,
        net_sales_pence=c.net_sales_pence,
        net_units=c.net_units,
    )


@router.get(
    "/channels",
    response_model=ChannelMixResponse,
    summary="Channel mix",
    description=(
        "Revenue and volume split by how the order reached the business. "
        "Answers whether third-party delivery earns its commission.\n\n"
        "`online`, `mixed` and `unknown` are kept distinct from the channels "
        "they might casually be folded into, because each records a different "
        "fact about the order's origin."
    ),
    responses=BAD_RANGE,
)
def channels(
    start_date: date = Query(..., description=_DATE_HELP),
    end_date: date = Query(..., description=_DATE_HELP),
    service: AnalyticsService = Depends(get_analytics_service),
) -> ChannelMixResponse:
    window, shares = _window_or_400(lambda: service.channel_mix(start_date, end_date))
    return ChannelMixResponse(
        start_date=window.start_date,
        end_date=window.end_date,
        channels=[
            ChannelMixEntry(
                channel=s.totals.channel,
                net_sales_pence=s.totals.net_sales_pence,
                payment_order_count=s.totals.payment_order_count,
                net_units=s.totals.net_units,
                average_order_value_pence=s.totals.average_order_value_pence,
                share_of_payment_orders_percent=s.share_of_payment_orders_percent,
                share_of_net_sales_percent=s.share_of_net_sales_percent,
            )
            for s in shares
        ],
    )
