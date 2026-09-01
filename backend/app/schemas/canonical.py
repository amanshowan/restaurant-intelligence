"""Canonical, vendor-neutral records produced by any source adapter.

These are plain data objects, not SQLAlchemy models: the adapter layer does not
touch the database (ARCHITECTURE.md §2). Persistence maps these onto the ORM
models separately.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import Channel, OrderEventType, ProductKind


class CanonicalProduct(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    #: Square's price point ("Regular"/"Large"); "" when the item has none.
    #: Never composed into `name` — the catalogue grain is (name, variation).
    variation: str = ""
    category: str | None = None
    kind: ProductKind = ProductKind.MENU_ITEM

    @property
    def key(self) -> tuple[str, str]:
        """Natural key, matching uq_products_name_variation."""
        return (self.name, self.variation)


class CanonicalOrderItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_order_id: str
    product: CanonicalProduct
    quantity: int
    #: Integer pence. `line_total` is authoritative; `unit_price` is derived.
    unit_price: int
    line_total: int
    #: Free-text modifier list, retained because it is the only thing that
    #: distinguishes two otherwise identical lines on the same order.
    modifiers: str | None = None


class CanonicalOrder(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    source_order_id: str
    source_payment_id: str | None = None
    #: Always UTC. Converted from the export's local wall time.
    occurred_at: datetime
    channel: Channel
    event_type: OrderEventType
    #: Integer pence, pre-discount: gross = net + discount.
    gross_amount: int
    discount_amount: int
    net_amount: int
    item_count: int = 0
