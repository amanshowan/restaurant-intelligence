"""Response schemas for product / menu analytics."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.analytics.service import MovementStatus
from app.models.enums import ProductKind

PENCE = "Integer minor units (pence). Never a float."

DISCOUNT_NOTE = (
    "Discount recorded by the source for this exact line, not apportioned from "
    "the order total."
)


class ProductIdentity(BaseModel):
    """A product variation. Regular and Large are different products."""

    model_config = ConfigDict(frozen=True)

    product_id: int = Field(description="Stable identifier for this variation.")
    name: str
    variation: str = Field(description='Price point, e.g. "Large". "" when none.')
    kind: ProductKind


class ProductPerformance(ProductIdentity):
    model_config = ConfigDict(frozen=True)

    gross_sales_pence: int = Field(description=f"{PENCE} Before discounts.")
    discounts_pence: int = Field(description=f"{PENCE} {DISCOUNT_NOTE}")
    net_sales_pence: int = Field(description=f"{PENCE} Gross less allocated discount.")
    net_units: int = Field(description="Units sold minus units refunded.")
    payment_order_count: int = Field(
        description="Distinct payment orders containing this product — not the "
        "number of lines. Three of one coffee on one order counts once. Refund "
        "events are excluded."
    )
    average_selling_price_pence: int | None = Field(
        default=None,
        description=f"{PENCE} Net sales per net unit; null when net units is "
        "not positive, where no selling price is meaningful.",
    )
    share_of_net_sales_percent: float | None = Field(
        default=None,
        description="Share of the filtered set's net sales. Computed over all "
        "matching products, not just those returned. Null when the total is "
        "not positive.",
    )
    share_of_units_percent: float | None = Field(default=None)


class ProductListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_date: date
    end_date: date
    kinds: list[ProductKind] = Field(
        description="Product kinds included. Defaults to menu_item only."
    )
    sort: Literal["net_sales", "gross_sales", "net_units", "discounts"]
    total_net_sales_pence: int = Field(
        description=f"{PENCE} Across every product matching `kinds`, before "
        "any limit is applied."
    )
    total_net_units: int
    products: list[ProductPerformance]


class ProductTrendBucket(BaseModel):
    model_config = ConfigDict(frozen=True)

    period_start: date = Field(
        description="Local bucket start; the Monday for weekly granularity."
    )
    gross_sales_pence: int
    discounts_pence: int
    net_sales_pence: int
    net_units: int
    payment_order_count: int


class ProductTrendResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_date: date
    end_date: date
    granularity: Literal["day", "week"]
    product: ProductPerformance
    buckets: list[ProductTrendBucket] = Field(
        description="Chronological, zero-filled so a period with no sales is "
        "an explicit zero rather than a gap."
    )


class ProductMovement(ProductIdentity):
    model_config = ConfigDict(frozen=True)

    current_net_sales_pence: int
    previous_net_sales_pence: int
    net_sales_change_pence: int
    net_sales_percent_change: float | None = Field(
        default=None,
        description="Null unless the previous period's net sales was positive. "
        "A product with no previous sales has not grown by infinity.",
    )
    current_net_units: int
    previous_net_units: int
    net_units_change: int
    status: MovementStatus = Field(
        description="Why the percentage is or is not defined. Describes the "
        "arithmetic only — no judgement about performance is implied."
    )


class ProductMoversResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_date: date
    end_date: date
    previous_start_date: date = Field(
        description="Start of the equal-length period immediately preceding."
    )
    previous_end_date: date
    kinds: list[ProductKind]
    movements: list[ProductMovement] = Field(
        description="Largest absolute change in net sales first. Products "
        "present in either period appear, so a disappearance is as visible as "
        "an arrival."
    )
