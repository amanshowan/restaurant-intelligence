"""Line item on an order."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:  # pragma: no cover
    from app.models.order import Order
    from app.models.product import Product


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)

    # CASCADE: a line item has no meaning without its order, so deleting the
    # order removes them at the database level.
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # RESTRICT: the opposite policy. Order items are historical financial
    # records; PostgreSQL will refuse to delete a product that has sales
    # history rather than silently erasing it. Retiring a product from the
    # catalogue is a soft-delete / deactivate operation, not a row delete.
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    quantity: Mapped[int] = mapped_column(nullable=False)

    # Integer pence, as with Order (§4).
    unit_price: Mapped[int] = mapped_column(nullable=False)
    line_total: Mapped[int] = mapped_column(nullable=False)

    order: Mapped["Order"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship(back_populates="order_items")

    def __repr__(self) -> str:
        return f"<OrderItem id={self.id} order_id={self.order_id} qty={self.quantity}>"
