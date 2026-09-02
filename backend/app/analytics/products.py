"""Product-level SQL aggregations.

Grain is the canonical product identity `(name, variation)` — one row per
variation, never merged. "Caffe Latte / Regular" and "Caffe Latte / Large" are
different products with different prices and are reported separately.

Discounts are read, not apportioned
-----------------------------------
`order_items.discount_amount` holds the discount Square reported for that exact
line, so a staff discount on one item of a five-item basket is attributed to the
item it was applied to. Nothing here divides an order total across lines.

An earlier draft apportioned the order-level discount pro-rata by line value.
Measured against the first real month that was exact for only 30% of discount
value — £231.40 of £767.31 — because 26 of 73 discounted orders contained more
than one product. Persisting the source value removed the approximation and the
rounding residual that came with it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import Date, cast, distinct, func, select
from sqlalchemy.orm import Session

from app.analytics.queries import Granularity, _bucket_expression
from app.analytics.windows import QueryWindow
from app.models import Order, OrderItem, Product
from app.models.enums import OrderEventType, ProductKind

#: Product/menu analytics answer "how is the menu performing", so non-menu
#: catalogue entries are excluded unless explicitly asked for. Gift vouchers are
#: a liability at issuance, not menu revenue, and "Custom Amount" is an
#: open-price line with no menu identity. Both stay in the database for source
#: reconciliation; they are filtered here, never deleted.
DEFAULT_KINDS: tuple[ProductKind, ...] = (ProductKind.MENU_ITEM,)


@dataclass(frozen=True)
class ProductTotals:
    product_id: int
    name: str
    variation: str
    kind: ProductKind
    gross_sales_pence: int = 0
    discounts_pence: int = 0
    net_sales_pence: int = 0
    net_units: int = 0
    payment_order_count: int = 0

    @property
    def average_selling_price_pence(self) -> int | None:
        """Net sales per net unit.

        None when net units is not positive: a product that was only refunded,
        or whose sales and refunds cancel out, has no meaningful selling price,
        and dividing by zero or a negative count would invent one.
        """
        if self.net_units <= 0:
            return None
        sign = -1 if self.net_sales_pence < 0 else 1
        total, units = abs(self.net_sales_pence), self.net_units
        return sign * ((total + units // 2) // units)


@dataclass(frozen=True)
class ProductBucket:
    period_start: date
    gross_sales_pence: int = 0
    discounts_pence: int = 0
    net_sales_pence: int = 0
    net_units: int = 0
    payment_order_count: int = 0


def _lines_cte(window: QueryWindow):
    """Order lines in the window, each carrying its order's gross total.

    The window predicate is applied to the raw `orders.occurred_at` column so it
    remains sargable against ix_orders_occurred_at; nothing here wraps that
    column in a function.
    """
    return (
        select(
            OrderItem.product_id.label("product_id"),
            OrderItem.line_total.label("line_total"),
            OrderItem.quantity.label("quantity"),
            Order.id.label("order_id"),
            Order.occurred_at.label("occurred_at"),
            Order.event_type.label("event_type"),
            OrderItem.discount_amount.label("line_discount"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.occurred_at >= window.start_utc,
            Order.occurred_at < window.end_utc,
        )
        .cte("windowed_lines")
    )


def _measures(lines):
    gross = func.coalesce(func.sum(lines.c.line_total), 0)
    discounts = func.coalesce(func.sum(lines.c.line_discount), 0)
    return (
        gross.label("gross_sales_pence"),
        discounts.label("discounts_pence"),
        (gross - discounts).label("net_sales_pence"),
        func.coalesce(func.sum(lines.c.quantity), 0).label("net_units"),
        # DISTINCT orders, not lines: an order with three of the same coffee is
        # one order. Refund events are excluded so they cannot inflate volume.
        func.count(distinct(lines.c.order_id))
        .filter(lines.c.event_type == OrderEventType.PAYMENT)
        .label("payment_order_count"),
    )


def fetch_product_totals(
    session: Session, window: QueryWindow, kinds: tuple[ProductKind, ...]
) -> list[ProductTotals]:
    """One row per product variation. Ordering and limiting happen in the service."""
    lines = _lines_cte(window)
    rows = session.execute(
        select(
            Product.id.label("product_id"),
            Product.name,
            Product.variation,
            Product.kind,
            *_measures(lines),
        )
        .select_from(lines)
        .join(Product, Product.id == lines.c.product_id)
        .where(Product.kind.in_(kinds))
        .group_by(Product.id, Product.name, Product.variation, Product.kind)
    ).all()

    return [
        ProductTotals(
            product_id=r.product_id,
            name=r.name,
            variation=r.variation,
            kind=r.kind,
            # int() is load-bearing: PostgreSQL's SUM() over a bigint returns
            # NUMERIC, which psycopg hands back as Decimal. Money is integer
            # pence everywhere in this codebase, so the boundary is enforced
            # here rather than left to leak into responses.
            gross_sales_pence=int(r.gross_sales_pence),
            discounts_pence=int(r.discounts_pence),
            net_sales_pence=int(r.net_sales_pence),
            net_units=int(r.net_units),
            payment_order_count=int(r.payment_order_count),
        )
        for r in rows
    ]


def fetch_product_trend(
    session: Session, window: QueryWindow, product_id: int, granularity: Granularity
) -> dict[date, ProductBucket]:
    """Time series for one product variation, keyed by local bucket start."""
    lines = _lines_cte(window)
    bucket = cast(
        _bucket_expression_for(lines, granularity), Date
    ).label("bucket")

    rows = session.execute(
        select(bucket, *_measures(lines))
        .select_from(lines)
        .where(lines.c.product_id == product_id)
        .group_by(bucket)
        .order_by(bucket)
    ).all()

    return {
        r.bucket: ProductBucket(
            period_start=r.bucket,
            gross_sales_pence=int(r.gross_sales_pence),
            discounts_pence=int(r.discounts_pence),
            net_sales_pence=int(r.net_sales_pence),
            net_units=int(r.net_units),
            payment_order_count=int(r.payment_order_count),
        )
        for r in rows
    }


def _bucket_expression_for(lines, granularity: Granularity):
    """Local-time bucket, mirroring app.analytics.queries but over the CTE."""
    from app.config import settings

    local = func.timezone(settings.business_timezone, lines.c.occurred_at)
    if granularity == "week":
        return func.date_trunc("week", local)
    return local


def product_exists(session: Session, product_id: int) -> Product | None:
    return session.get(Product, product_id)
