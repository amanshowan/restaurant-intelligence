"""External Square export schemas.

These mirror Square's columns, not ours. They exist so the vendor's shape is
validated and named in exactly one place (ARCHITECTURE.md §2); nothing outside
the Square adapter should import them.

`extra="ignore"` is the mechanism by which customer, card and staff columns
never enter the application at all: unlisted columns are not bound, so PII is
dropped at the boundary rather than being carried and later filtered.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _SquareRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore", frozen=True)


class SquareTransactionRow(_SquareRow):
    """One row of the Transactions export."""

    date: str = Field(alias="Date")
    time: str = Field(alias="Time")
    time_zone: str = Field(alias="Time Zone")

    gross_sales: str = Field(alias="Gross Sales")
    discounts: str = Field(alias="Discounts")
    net_sales: str = Field(alias="Net Sales")

    transaction_id: str = Field(alias="Transaction ID")
    payment_id: str = Field(alias="Payment ID", default="")

    event_type: str = Field(alias="Event Type")
    source: str = Field(alias="Source", default="")
    dining_option: str = Field(alias="Dining Option", default="")


class SquareItemRow(_SquareRow):
    """One row of the Items Detail export."""

    date: str = Field(alias="Date")
    time: str = Field(alias="Time")
    time_zone: str = Field(alias="Time Zone")

    category: str = Field(alias="Category", default="")
    item: str = Field(alias="Item")
    qty: str = Field(alias="Qty")
    price_point_name: str = Field(alias="Price Point Name", default="")
    modifiers_applied: str = Field(alias="Modifiers Applied", default="")

    product_sales: str = Field(alias="Product Sales")
    discounts: str = Field(alias="Discounts", default="")
    net_sales: str = Field(alias="Net Sales", default="")

    transaction_id: str = Field(alias="Transaction ID")
    event_type: str = Field(alias="Event Type", default="Payment")


class SquareSummaryRow(_SquareRow):
    """One row of the Items Summary export — reconciliation only.

    Never becomes a canonical sales record. It is Square's own aggregation,
    used as an independent oracle to check our computed totals.
    """

    item_name: str = Field(alias="Item Name")
    item_variation: str = Field(alias="Item Variation", default="")
    category: str = Field(alias="Category", default="")

    items_sold: str = Field(alias="Items Sold", default="0")
    items_refunded: str = Field(alias="Items Refunded", default="0")
    units_sold: str = Field(alias="Units Sold", default="0")

    product_sales: str = Field(alias="Product Sales", default="")
    refunds: str = Field(alias="Refunds", default="")
    discounts: str = Field(alias="Discounts & Comps", default="")
    net_sales: str = Field(alias="Net Sales", default="")
    gross_sales: str = Field(alias="Gross Sales", default="")
