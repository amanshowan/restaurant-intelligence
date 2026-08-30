"""Product catalogue."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for type checkers only
    from app.models.order_item import OrderItem


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # No delete cascade, deliberately: order items are historical financial
    # records and must survive a product being removed from the catalogue.
    # The RESTRICT on OrderItem.product_id makes the database refuse to delete
    # a product that has sales history at all.
    #
    # passive_deletes="all" stops SQLAlchemy nulling out order_items.product_id
    # before the delete. Without it the failure still occurs, but as a NOT NULL
    # violation on that UPDATE rather than the foreign key doing its job — the
    # right outcome for the wrong reason, and one that would stop protecting us
    # the moment the column became nullable.
    order_items: Mapped[list["OrderItem"]] = relationship(
        back_populates="product", passive_deletes="all"
    )

    def __repr__(self) -> str:
        return f"<Product id={self.id} name={self.name!r}>"
