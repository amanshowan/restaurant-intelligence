"""Menu evidence endpoint."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from app.analytics.products import DEFAULT_KINDS
from app.analytics.service import AnalyticsService
from app.api.deps import get_analytics_service
from app.api.products import ERRORS, _guard, _kinds
from app.models.enums import ProductKind
from app.schemas.menu import (
    AttachmentEvidenceEntry,
    EvidenceProduct,
    MenuEvidenceResponse,
    MenuEvidenceRowResponse,
)

router = APIRouter(prefix="/analytics/menu", tags=["analytics"])

_DATE_HELP = (
    "Inclusive local calendar date (Europe/London), not UTC. The final day is "
    "included in full."
)


def _product(ref) -> EvidenceProduct:
    return EvidenceProduct(
        product_id=ref.product_id, name=ref.name, variation=ref.variation
    )


@router.get(
    "/evidence",
    response_model=MenuEvidenceResponse,
    summary="Measured evidence per menu product",
    description=(
        "One row per product variation combining performance, movement against "
        "the comparable previous period, and its strongest co-purchase "
        "association.\n\n"
        "This is an evidence view, not a recommendation engine. It reports what "
        "was measured and nothing more: assessing whether a product should be "
        "repriced, promoted or removed needs cost, margin and price-elasticity "
        "data that this system does not hold."
    ),
    responses=ERRORS,
)
def menu_evidence(
    start_date: date = Query(..., description=_DATE_HELP),
    end_date: date = Query(..., description=_DATE_HELP),
    limit: int | None = Query(
        None, ge=1, le=1000,
        description="Maximum rows returned, highest net sales first.",
    ),
    min_pair_orders: int = Query(
        5, ge=1,
        description="Attachment evidence below this co-occurrence count is "
        "omitted. Raising it makes the reported lift more trustworthy.",
    ),
    kind: list[ProductKind] | None = Query(
        None,
        description="Product kinds to include; repeat for several. Defaults to "
        "menu_item only — gift vouchers and open-price lines are not menu "
        "products and would distort the view.",
    ),
    service: AnalyticsService = Depends(get_analytics_service),
) -> MenuEvidenceResponse:
    evidence = _guard(
        lambda: service.menu_evidence(
            start_date, end_date,
            kinds=_kinds(kind, DEFAULT_KINDS),
            min_pair_orders=min_pair_orders,
            limit=limit,
        )
    )
    return MenuEvidenceResponse(
        start_date=evidence.window.start_date,
        end_date=evidence.window.end_date,
        previous_start_date=evidence.previous_window.start_date,
        previous_end_date=evidence.previous_window.end_date,
        kinds=list(evidence.kinds),
        min_pair_orders=evidence.min_pair_orders,
        eligible_order_count=evidence.eligible_order_count,
        total_net_sales_pence=evidence.total_net_sales_pence,
        total_net_units=evidence.total_net_units,
        rows=[
            MenuEvidenceRowResponse(
                product=_product(r.product),
                kind=r.kind,
                gross_sales_pence=r.gross_sales_pence,
                discounts_pence=r.discounts_pence,
                net_sales_pence=r.net_sales_pence,
                net_units=r.net_units,
                payment_order_count=r.payment_order_count,
                average_selling_price_pence=r.average_selling_price_pence,
                discount_rate_percent=r.discount_rate_percent,
                share_of_menu_net_sales_percent=r.share_of_menu_net_sales_percent,
                share_of_menu_units_percent=r.share_of_menu_units_percent,
                previous_net_sales_pence=r.previous_net_sales_pence,
                previous_net_units=r.previous_net_units,
                net_sales_change_pence=r.net_sales_change_pence,
                net_units_change=r.net_units_change,
                net_sales_percent_change=r.net_sales_percent_change,
                movement_status=r.movement_status,
                revenue_direction=r.revenue_direction,
                strongest_attachment=(
                    AttachmentEvidenceEntry(
                        product=_product(r.strongest_attachment.product),
                        pair_orders=r.strongest_attachment.pair_orders,
                        attachment_rate_percent=(
                            r.strongest_attachment.attachment_rate_percent
                        ),
                        lift=r.strongest_attachment.lift,
                    )
                    if r.strongest_attachment
                    else None
                ),
            )
            for r in evidence.rows
        ],
    )
