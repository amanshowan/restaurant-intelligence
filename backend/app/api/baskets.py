"""Basket / co-purchase endpoints."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.analytics.baskets import DEFAULT_KINDS
from app.analytics.service import AnalyticsService
from app.api.deps import get_analytics_service
from app.api.products import ERRORS, _guard, _kinds
from app.models.enums import ProductKind
from app.schemas.baskets import (
    BasketProduct,
    ProductPairEntry,
    ProductPairsResponse,
)

router = APIRouter(prefix="/analytics/baskets", tags=["analytics"])

_DATE_HELP = (
    "Inclusive local calendar date (Europe/London), not UTC. The final day is "
    "included in full."
)
MIN_PAIR_HELP = (
    "Exclude pairs seen fewer times than this. Raise it before reading `lift`: "
    "a pair occurring once or twice can show an extreme lift from a sample far "
    "too small to mean anything."
)
KIND_HELP = (
    "Product kinds to include; repeat for several. Defaults to menu_item only, "
    "since gift vouchers and open-price lines are not menu products and would "
    "distort co-purchase structure."
)


def _ref(product) -> BasketProduct:
    return BasketProduct(
        product_id=product.product_id, name=product.name, variation=product.variation
    )


@router.get(
    "/pairs",
    response_model=ProductPairsResponse,
    summary="Products bought together",
    description=(
        "Unordered co-purchase pairs across payment orders, with support, "
        "confidence in both directions, and lift.\n\n"
        "Co-occurrence counts distinct ORDERS, not quantities: three of an item "
        "on one order counts once, and repeated lines of the same product do "
        "not multiply the count. Refunds are excluded — a refund neither "
        "creates nor cancels the fact that two items were bought together.\n\n"
        "This endpoint reports association evidence only. A high lift is not a "
        "recommendation, and no significance testing is implied."
    ),
    responses=ERRORS,
)
def product_pairs(
    start_date: date = Query(..., description=_DATE_HELP),
    end_date: date = Query(..., description=_DATE_HELP),
    min_pair_orders: int = Query(1, ge=1, description=MIN_PAIR_HELP),
    sort: Literal["pair_orders", "lift", "support"] = Query(
        "pair_orders", description="Ranking measure, highest first."
    ),
    limit: int | None = Query(
        None, ge=1, le=1000, description="Maximum pairs returned."
    ),
    kind: list[ProductKind] | None = Query(None, description=KIND_HELP),
    service: AnalyticsService = Depends(get_analytics_service),
) -> ProductPairsResponse:
    kinds = _kinds(kind, DEFAULT_KINDS)
    analysis = _guard(
        lambda: service.product_pairs(
            start_date, end_date, kinds=kinds,
            min_pair_orders=min_pair_orders, sort=sort, limit=limit,
        )
    )
    return ProductPairsResponse(
        start_date=analysis.window.start_date,
        end_date=analysis.window.end_date,
        kinds=list(analysis.kinds),
        sort=analysis.sort,
        min_pair_orders=analysis.min_pair_orders,
        eligible_order_count=analysis.eligible_order_count,
        distinct_product_count=analysis.distinct_product_count,
        qualifying_pair_count=analysis.qualifying_pair_count,
        pairs=[
            ProductPairEntry(
                product_a=_ref(p.counts.a),
                product_b=_ref(p.counts.b),
                pair_orders=p.counts.pair_orders,
                product_a_orders=p.counts.a_orders,
                product_b_orders=p.counts.b_orders,
                support_percent=p.metrics.support_percent,
                confidence_a_to_b_percent=p.metrics.confidence_a_to_b_percent,
                confidence_b_to_a_percent=p.metrics.confidence_b_to_a_percent,
                lift=p.metrics.lift,
            )
            for p in analysis.pairs
        ],
    )
