"""Basket composition, co-purchase and attachment aggregations.

Everything here derives from one relation: the DISTINCT set of
`(payment order, product)` pairs in the window. Building that first is what
makes the rest correct and cheap.

  * DISTINCT collapses quantity and repeated lines, so three coffees on one
    order — or the same product on two lines differing only by modifiers —
    counts once. Co-occurrence is about which orders contained what, not how
    much of it.
  * Only `event_type = 'payment'` rows enter. A refund is not a basket: it
    neither creates nor cancels the fact that two products were bought
    together, so refund events are excluded rather than subtracted.
  * Pairs come from a self-join with `a.product_id < b.product_id`, which in
    one condition makes each unordered pair appear exactly once and rules out
    self-pairs.

Metric definitions, computed from integer counts:

    support(A,B)     = orders containing both / eligible payment orders
    confidence(A→B)  = orders containing both / orders containing A
    confidence(B→A)  = orders containing both / orders containing B
    lift(A,B)        = support(A,B) / (support(A) × support(B))
                     = (pair_orders × eligible) / (orders_A × orders_B)

Lift is reported alongside the raw pair count on purpose. A pair seen twice can
show enormous lift, and that number means very little; the count is what tells
a reader whether to believe it.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.analytics.windows import QueryWindow
from app.models import Order, OrderItem, Product
from app.models.enums import OrderEventType, ProductKind

#: Basket analysis is about the menu. Gift vouchers and open-price lines are
#: excluded by default for the same reason as elsewhere: neither is a menu
#: product, and both would distort co-purchase structure.
DEFAULT_KINDS: tuple[ProductKind, ...] = (ProductKind.MENU_ITEM,)


@dataclass(frozen=True)
class ProductRef:
    product_id: int
    name: str
    variation: str


@dataclass(frozen=True)
class PairCounts:
    a: ProductRef
    b: ProductRef
    pair_orders: int
    a_orders: int
    b_orders: int


@dataclass(frozen=True)
class AttachmentCounts:
    product: ProductRef
    pair_orders: int
    product_orders: int


def basket_cte(window: QueryWindow, kinds: tuple[ProductKind, ...]):
    """DISTINCT (order_id, product_id) for eligible payment orders.

    The window predicate stays on the raw `orders.occurred_at` column so it
    remains sargable against ix_orders_occurred_at.
    """
    return (
        select(
            Order.id.label("order_id"),
            OrderItem.product_id.label("product_id"),
        )
        .join(OrderItem, OrderItem.order_id == Order.id)
        .join(Product, Product.id == OrderItem.product_id)
        .where(
            Order.occurred_at >= window.start_utc,
            Order.occurred_at < window.end_utc,
            Order.event_type == OrderEventType.PAYMENT,
            Product.kind.in_(kinds),
        )
        .distinct()
        .cte("basket")
    )


def fetch_eligible_order_count(
    session: Session, window: QueryWindow, kinds: tuple[ProductKind, ...]
) -> int:
    """Payment orders containing at least one product of the included kinds.

    This is the support denominator. Orders holding only excluded kinds, or no
    lines at all, are not part of the population being analysed and would
    otherwise deflate every support figure.
    """
    basket = basket_cte(window, kinds)
    return int(
        session.execute(
            select(func.count(distinct(basket.c.order_id))).select_from(basket)
        ).scalar()
        or 0
    )


def fetch_product_order_counts(
    session: Session, window: QueryWindow, kinds: tuple[ProductKind, ...]
) -> dict[int, int]:
    """Distinct payment orders containing each product."""
    basket = basket_cte(window, kinds)
    rows = session.execute(
        select(basket.c.product_id, func.count().label("orders"))
        .select_from(basket)
        .group_by(basket.c.product_id)
    ).all()
    return {row.product_id: int(row.orders) for row in rows}


def fetch_pairs(
    session: Session,
    window: QueryWindow,
    kinds: tuple[ProductKind, ...],
    min_pair_orders: int,
    product_orders: dict[int, int],
) -> list[PairCounts]:
    """Unordered product pairs and their co-occurrence counts.

    `product_orders` is passed in rather than re-queried: the caller already
    needs it, and computing the same aggregate twice per request is waste.
    """
    basket = basket_cte(window, kinds)
    left = basket.alias("left_side")
    right = basket.alias("right_side")

    product_a = Product.__table__.alias("product_a")
    product_b = Product.__table__.alias("product_b")

    pair_orders = func.count().label("pair_orders")

    rows = session.execute(
        select(
            left.c.product_id.label("a_id"),
            product_a.c.name.label("a_name"),
            product_a.c.variation.label("a_variation"),
            right.c.product_id.label("b_id"),
            product_b.c.name.label("b_name"),
            product_b.c.variation.label("b_variation"),
            pair_orders,
        )
        .select_from(left)
        .join(
            right,
            # `<` rather than `<>`: each unordered pair once, and never (A,A).
            (left.c.order_id == right.c.order_id)
            & (left.c.product_id < right.c.product_id),
        )
        .join(product_a, product_a.c.id == left.c.product_id)
        .join(product_b, product_b.c.id == right.c.product_id)
        .group_by(
            left.c.product_id, product_a.c.name, product_a.c.variation,
            right.c.product_id, product_b.c.name, product_b.c.variation,
        )
        .having(func.count() >= min_pair_orders)
    ).all()

    return [
        PairCounts(
            a=ProductRef(row.a_id, row.a_name, row.a_variation),
            b=ProductRef(row.b_id, row.b_name, row.b_variation),
            pair_orders=int(row.pair_orders),
            a_orders=product_orders.get(row.a_id, 0),
            b_orders=product_orders.get(row.b_id, 0),
        )
        for row in rows
    ]


def fetch_attachments(
    session: Session,
    window: QueryWindow,
    anchor_id: int,
    kinds: tuple[ProductKind, ...],
    min_pair_orders: int,
    product_orders: dict[int, int],
) -> tuple[int, list[AttachmentCounts]]:
    """Products co-occurring with `anchor_id`, and the anchor's own order count.

    The anchor's own count is read from `product_orders` rather than queried
    separately — it is the same aggregate.
    """
    basket = basket_cte(window, kinds)
    anchor = basket.alias("anchor")
    other = basket.alias("other")
    product = Product.__table__.alias("attached_product")

    anchor_orders = product_orders.get(anchor_id, 0)

    rows = session.execute(
        select(
            other.c.product_id.label("product_id"),
            product.c.name,
            product.c.variation,
            func.count().label("pair_orders"),
        )
        .select_from(anchor)
        .join(
            other,
            (anchor.c.order_id == other.c.order_id)
            & (other.c.product_id != anchor.c.product_id),
        )
        .join(product, product.c.id == other.c.product_id)
        .where(anchor.c.product_id == anchor_id)
        .group_by(other.c.product_id, product.c.name, product.c.variation)
        .having(func.count() >= min_pair_orders)
    ).all()

    attachments = [
        AttachmentCounts(
            product=ProductRef(row.product_id, row.name, row.variation),
            pair_orders=int(row.pair_orders),
            product_orders=product_orders.get(row.product_id, 0),
        )
        for row in rows
    ]
    return anchor_orders, attachments
