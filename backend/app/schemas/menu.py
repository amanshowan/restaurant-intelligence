"""Response schemas for the menu evidence view.

This is a decision-EVIDENCE surface, not a recommendation engine. It reports
what was measured. It deliberately contains no field that says a product should
be repriced, promoted or removed: those claims need cost, margin and
price-elasticity data, none of which this system holds. Status fields describe
arithmetic only.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.analytics.service import MovementStatus, RevenueDirection
from app.models.enums import ProductKind

PENCE = "Integer minor units (pence). Never a float."


class EvidenceProduct(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: int
    name: str
    variation: str = Field(description='Price point; "" when the item has none.')


class AttachmentEvidenceEntry(BaseModel):
    """The strongest qualifying co-purchase association for this product."""

    model_config = ConfigDict(frozen=True)

    product: EvidenceProduct
    pair_orders: int = Field(
        description="Distinct payment orders containing both products."
    )
    attachment_rate_percent: float | None = Field(
        default=None,
        description="orders containing both / orders containing this row's "
        "product.",
    )
    lift: float | None = Field(
        default=None,
        description="How much more often the two appear together than "
        "independence predicts. Read WITH `pair_orders`: a small sample can "
        "produce a large lift that means little.",
    )


class MenuEvidenceRowResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    product: EvidenceProduct
    kind: ProductKind

    gross_sales_pence: int = Field(description=f"{PENCE} Before discounts.")
    discounts_pence: int = Field(
        description=f"{PENCE} Exact per-line values from the source export, "
        "not apportioned from the order total."
    )
    net_sales_pence: int = Field(description=f"{PENCE} Gross less discounts.")
    net_units: int = Field(description="Units sold minus units refunded.")
    payment_order_count: int = Field(
        description="Distinct payment orders containing this product."
    )

    average_selling_price_pence: int | None = Field(
        default=None,
        description=f"{PENCE} Net sales per net unit; null when net units is "
        "not positive.",
    )
    discount_rate_percent: float | None = Field(
        default=None,
        description="discount_amount / gross_sales. Null when gross sales is "
        "not positive, where the rate would be undefined or misleading.",
    )
    share_of_menu_net_sales_percent: float | None = None
    share_of_menu_units_percent: float | None = None

    previous_net_sales_pence: int = Field(
        description=f"{PENCE} Same measure over the comparable previous period."
    )
    previous_net_units: int
    net_sales_change_pence: int
    net_units_change: int
    net_sales_percent_change: float | None = Field(
        default=None,
        description="Null unless the previous period's net sales was positive.",
    )
    movement_status: MovementStatus = Field(
        description="Why the percentage is or is not defined. Arithmetic only."
    )
    revenue_direction: RevenueDirection = Field(
        description="Sign of the change in net sales. Factual, not a judgement."
    )

    strongest_attachment: AttachmentEvidenceEntry | None = Field(
        default=None,
        description="Highest-lift qualifying co-purchase partner, or null when "
        "no pairing meets `min_pair_orders`.",
    )


class MenuEvidenceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_date: date
    end_date: date
    previous_start_date: date = Field(
        description="Start of the equal-length period immediately preceding."
    )
    previous_end_date: date
    kinds: list[ProductKind] = Field(
        description="Product kinds included. Defaults to menu_item only."
    )
    min_pair_orders: int = Field(
        description="Attachment evidence below this co-occurrence count is "
        "omitted rather than reported weakly."
    )

    eligible_order_count: int = Field(
        description="Payment orders containing at least one included product."
    )
    total_net_sales_pence: int = Field(
        description=f"{PENCE} Across every matching product, before `limit`."
    )
    total_net_units: int

    rows: list[MenuEvidenceRowResponse] = Field(
        description="Highest net sales first. Evidence only — no field here "
        "recommends an action."
    )
