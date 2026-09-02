"""Product / menu analytics endpoints.

Thin handlers: validate, delegate to the analytics service, shape the response.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app.analytics.products import DEFAULT_KINDS
from app.analytics.service import AnalyticsService
from app.analytics.windows import InvalidDateRange
from app.api.deps import get_analytics_service
from app.models.enums import ProductKind
from app.schemas.imports import ErrorResponse
from app.schemas.products import (
    ProductListResponse,
    ProductMoversResponse,
    ProductMovement,
    ProductPerformance,
    ProductTrendBucket,
    ProductTrendResponse,
)

router = APIRouter(prefix="/analytics/products", tags=["analytics"])

_DATE_HELP = (
    "Inclusive local calendar date (Europe/London), not UTC. The final day is "
    "included in full."
)
_KIND_HELP = (
    "Product kinds to include; repeat for several. Defaults to menu_item only. "
    "Gift vouchers are a liability at issuance rather than menu revenue, and "
    "custom (open-price) lines have no menu identity, so both are excluded "
    "unless asked for. They remain in the database for source reconciliation."
)

ERRORS = {
    400: {"model": ErrorResponse, "description": "Invalid date range"},
    422: {"model": ErrorResponse, "description": "Missing or malformed parameter"},
}
ERRORS_WITH_404 = {
    **ERRORS,
    404: {"model": ErrorResponse, "description": "Unknown product"},
}


def _guard(call):
    try:
        return call()
    except InvalidDateRange as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"detail": str(exc), "code": "invalid_date_range"},
        ) from exc


def _kinds(selected: list[ProductKind] | None) -> tuple[ProductKind, ...]:
    return tuple(dict.fromkeys(selected)) if selected else DEFAULT_KINDS


def _performance(share) -> ProductPerformance:
    t = share.totals
    return ProductPerformance(
        product_id=t.product_id,
        name=t.name,
        variation=t.variation,
        kind=t.kind,
        gross_sales_pence=t.gross_sales_pence,
        discounts_pence=t.discounts_pence,
        net_sales_pence=t.net_sales_pence,
        net_units=t.net_units,
        payment_order_count=t.payment_order_count,
        average_selling_price_pence=t.average_selling_price_pence,
        share_of_net_sales_percent=share.share_of_net_sales_percent,
        share_of_units_percent=share.share_of_units_percent,
    )


@router.get(
    "",
    response_model=ProductListResponse,
    summary="Product performance ranking",
    description=(
        "Menu performance by product variation. Variations are never merged: "
        '"Caffe Latte / Regular" and "Caffe Latte / Large" are different '
        "products at different prices and are reported separately.\\n\\n"
        "Shares are computed across every matching product before `limit` is "
        "applied, so a top-10 list still shows each product's share of the "
        "whole menu."
    ),
    responses=ERRORS,
)
def list_products(
    start_date: date = Query(..., description=_DATE_HELP),
    end_date: date = Query(..., description=_DATE_HELP),
    sort: Literal["net_sales", "gross_sales", "net_units", "discounts"] = Query(
        "net_sales", description="Ranking measure, highest first."
    ),
    limit: int | None = Query(
        None, ge=1, le=1000, description="Maximum products returned."
    ),
    kind: list[ProductKind] | None = Query(None, description=_KIND_HELP),
    service: AnalyticsService = Depends(get_analytics_service),
) -> ProductListResponse:
    kinds = _kinds(kind)
    ranking = _guard(
        lambda: service.products(
            start_date, end_date, kinds=kinds, sort=sort, limit=limit
        )
    )
    return ProductListResponse(
        start_date=ranking.window.start_date,
        end_date=ranking.window.end_date,
        kinds=list(ranking.kinds),
        sort=ranking.sort,
        total_net_sales_pence=ranking.total_net_sales_pence,
        total_net_units=ranking.total_net_units,
        products=[_performance(p) for p in ranking.products],
    )


@router.get(
    "/movers",
    response_model=ProductMoversResponse,
    summary="Products gaining or losing momentum",
    description=(
        "Compares each product against the equal-length period immediately "
        "preceding the requested one — 15-31 August (17 days) compares with "
        "the 17 days ending 14 August.\\n\\n"
        "Reports measurable movement only. Nothing here labels a product good "
        "or bad; that judgement needs cost data this system does not hold."
    ),
    responses=ERRORS,
)
def product_movers(
    start_date: date = Query(..., description=_DATE_HELP),
    end_date: date = Query(..., description=_DATE_HELP),
    limit: int | None = Query(
        None, ge=1, le=1000,
        description="Maximum movements returned, largest absolute change first.",
    ),
    kind: list[ProductKind] | None = Query(None, description=_KIND_HELP),
    service: AnalyticsService = Depends(get_analytics_service),
) -> ProductMoversResponse:
    kinds = _kinds(kind)
    movers = _guard(
        lambda: service.product_movers(
            start_date, end_date, kinds=kinds, limit=limit
        )
    )
    return ProductMoversResponse(
        start_date=movers.window.start_date,
        end_date=movers.window.end_date,
        previous_start_date=movers.previous_window.start_date,
        previous_end_date=movers.previous_window.end_date,
        kinds=list(movers.kinds),
        movements=[
            ProductMovement(
                product_id=m.product_id,
                name=m.name,
                variation=m.variation,
                kind=m.kind,
                current_net_sales_pence=m.current_net_sales_pence,
                previous_net_sales_pence=m.previous_net_sales_pence,
                net_sales_change_pence=m.net_sales_change_pence,
                net_sales_percent_change=m.net_sales_percent_change,
                current_net_units=m.current_net_units,
                previous_net_units=m.previous_net_units,
                net_units_change=m.net_units_change,
                status=m.status,
            )
            for m in movers.movements
        ],
    )


@router.get(
    "/{product_id}/trend",
    response_model=ProductTrendResponse,
    summary="One product's performance over time",
    description=(
        "Time series for a single product variation, bucketed by local trading "
        "day or Monday-start week. Periods with no sales are explicit zero "
        "buckets, consistent with /analytics/revenue."
    ),
    responses=ERRORS_WITH_404,
)
def product_trend(
    product_id: int = Path(..., ge=1, description="Product variation identifier."),
    start_date: date = Query(..., description=_DATE_HELP),
    end_date: date = Query(..., description=_DATE_HELP),
    granularity: Literal["day", "week"] = Query(
        "day", description="Bucket size. Weekly buckets start on Monday."
    ),
    service: AnalyticsService = Depends(get_analytics_service),
) -> ProductTrendResponse:
    trend = _guard(
        lambda: service.product_trend(product_id, start_date, end_date, granularity)
    )
    if trend is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={
                "detail": f"no product with id {product_id}",
                "code": "product_not_found",
            },
        )

    t = trend.product
    return ProductTrendResponse(
        start_date=trend.window.start_date,
        end_date=trend.window.end_date,
        granularity=trend.granularity,
        product=ProductPerformance(
            product_id=t.product_id,
            name=t.name,
            variation=t.variation,
            kind=t.kind,
            gross_sales_pence=t.gross_sales_pence,
            discounts_pence=t.discounts_pence,
            net_sales_pence=t.net_sales_pence,
            net_units=t.net_units,
            payment_order_count=t.payment_order_count,
            average_selling_price_pence=t.average_selling_price_pence,
        ),
        buckets=[
            ProductTrendBucket(
                period_start=b.period_start,
                gross_sales_pence=b.gross_sales_pence,
                discounts_pence=b.discounts_pence,
                net_sales_pence=b.net_sales_pence,
                net_units=b.net_units,
                payment_order_count=b.payment_order_count,
            )
            for b in trend.buckets
        ],
    )
