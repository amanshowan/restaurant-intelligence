"""Response schemas for basket / co-purchase analytics."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ProductKind

_UNDEFINED = "Null when the denominator is zero — an undefined ratio, not a zero one."

_LIFT = (
    "support(A,B) / (support(A) × support(B)). 1.0 means the two products "
    "appear together exactly as often as independence would predict; above 1.0 "
    "means more often. Read it WITH `pair_orders`: a pair seen twice can show "
    "a very high lift that means almost nothing."
)


class BasketProduct(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: int
    name: str
    variation: str = Field(description='Price point; "" when the item has none.')


class ProductPairEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_a: BasketProduct
    product_b: BasketProduct

    pair_orders: int = Field(
        description="Distinct payment orders containing both products. "
        "Quantity is irrelevant: three of an item on one order counts once."
    )
    product_a_orders: int = Field(description="Payment orders containing A.")
    product_b_orders: int = Field(description="Payment orders containing B.")

    support_percent: float | None = Field(
        default=None,
        description=f"orders containing both / eligible payment orders. {_UNDEFINED}",
    )
    confidence_a_to_b_percent: float | None = Field(
        default=None,
        description=f"orders containing both / orders containing A. {_UNDEFINED}",
    )
    confidence_b_to_a_percent: float | None = Field(
        default=None,
        description=f"orders containing both / orders containing B. {_UNDEFINED}",
    )
    lift: float | None = Field(default=None, description=_LIFT)


class ProductPairsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_date: date
    end_date: date
    kinds: list[ProductKind] = Field(
        description="Product kinds included. Defaults to menu_item only."
    )
    sort: Literal["pair_orders", "lift", "support"]
    min_pair_orders: int = Field(
        description="Pairs occurring fewer times than this are excluded."
    )

    eligible_order_count: int = Field(
        description="Payment orders containing at least one product of the "
        "included kinds. This is the denominator for support."
    )
    distinct_product_count: int = Field(
        description="Distinct product variations appearing in those orders."
    )
    qualifying_pair_count: int = Field(
        description="Pairs meeting `min_pair_orders`, before `limit` is applied."
    )
    pairs: list[ProductPairEntry] = Field(
        description="Each unordered pair appears exactly once; (A,A) never appears."
    )


class AttachmentEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    product: BasketProduct
    pair_orders: int = Field(
        description="Payment orders containing both the anchor and this product."
    )
    product_orders: int = Field(
        description="Payment orders containing this product at all."
    )
    attachment_rate_percent: float | None = Field(
        default=None,
        description="orders containing anchor AND this / orders containing the "
        f"anchor. {_UNDEFINED}",
    )
    reverse_attachment_rate_percent: float | None = Field(
        default=None,
        description="orders containing both / orders containing THIS product. "
        "High when the attached product rarely appears without the anchor.",
    )
    support_percent: float | None = Field(default=None)
    lift: float | None = Field(default=None, description=_LIFT)


class ProductAttachmentsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_date: date
    end_date: date
    kinds: list[ProductKind]
    min_pair_orders: int

    anchor: BasketProduct
    anchor_order_count: int = Field(
        description="Eligible payment orders containing the anchor product."
    )
    eligible_order_count: int
    attachments: list[AttachmentEntry] = Field(
        description="Most co-occurring first, ties broken by name then variation."
    )
