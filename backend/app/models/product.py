"""Product catalogue."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SAEnum, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import ProductKind

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for type checkers only
    from app.models.order_item import OrderItem


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        # The catalogue grain is (name, variation), not name alone: the real
        # export has 133 distinct item names but 141 distinct (item, price
        # point) pairs. Keying on name alone would merge "Caffe Latte"
        # Regular and Large into one product at a blended price.
        #
        # Category is deliberately NOT part of the key — it is functionally
        # determined by (name, variation), so including it would fracture a
        # product into duplicates if Square ever recategorises it.
        UniqueConstraint("name", "variation", name="uq_products_name_variation"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Square's "Price Point Name" (Regular / Large / blank). Kept separate from
    # the display name rather than composed into it.
    #
    # NOT NULL DEFAULT '' is load-bearing, not laziness: PostgreSQL treats
    # NULLs as DISTINCT under a unique constraint, so a nullable column would
    # let two ('Caffe Latte', NULL) rows both exist — silently failing to
    # deduplicate the ~4,700 rows that have no price point at all.
    variation: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default="", default=""
    )
    category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # What this entry represents commercially. Gift vouchers are ingested so
    # reconciliation stays exact, but are excluded from operating revenue by
    # filtering on this field rather than on a brittle name/category match.
    kind: Mapped[ProductKind] = mapped_column(
        SAEnum(
            ProductKind,
            native_enum=False,
            create_constraint=False,
            length=32,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        server_default=ProductKind.MENU_ITEM.value,
        default=ProductKind.MENU_ITEM,
    )

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
