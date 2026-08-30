"""Canonical order — vendor-neutral, not Square's shape (§2)."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import Channel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.import_batch import ImportBatch
    from app.models.order_item import OrderItem


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        # Row-level deduplication enforced by the database, not by importer
        # code (§4) — the constraint holds even if the importer has a bug.
        UniqueConstraint("source", "source_order_id", name="uq_orders_source_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # Which system this came from ("square"). Plain VARCHAR rather than an
    # enum: a new source is an adapter, and should not need a schema change.
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_order_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Business event time, timezone-aware (TIMESTAMPTZ). Indexed because every
    # analytics query in §5 filters or groups by it.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # VARCHAR, not a native Postgres enum — see app/models/enums.py.
    channel: Mapped[Channel] = mapped_column(
        SAEnum(
            Channel,
            native_enum=False,
            create_constraint=False,
            length=32,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )

    # Money in integer minor units (pence), never floats (§4). Float
    # arithmetic on currency accumulates rounding error.
    gross_amount: Mapped[int] = mapped_column(nullable=False)
    discount_amount: Mapped[int] = mapped_column(nullable=False, default=0)
    net_amount: Mapped[int] = mapped_column(nullable=False)
    item_count: Mapped[int] = mapped_column(nullable=False, default=0)

    # Provenance / lineage. RESTRICT: an import batch is an audit record and
    # cannot be deleted while any order still references it. Rolling back an
    # import is therefore an explicit two-step operation — delete the imported
    # orders, then the batch — rather than an implicit side effect of a
    # foreign key. Nullable because orders may arrive without a batch (seed
    # data, or a future direct API integration).
    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    import_batch: Mapped["ImportBatch | None"] = relationship(back_populates="orders")

    # Two independent cascades, both required:
    #   cascade="all, delete-orphan"  ORM-level, for session.delete(order)
    #   passive_deletes=True          lets the DATABASE do the delete instead
    #                                 of SQLAlchemy loading every child row
    # The matching ON DELETE CASCADE lives on OrderItem.order_id, which also
    # covers deletes issued as raw SQL, outside the ORM entirely.
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Order id={self.id} source={self.source!r} net={self.net_amount}>"
