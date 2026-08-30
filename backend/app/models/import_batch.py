"""Record of a single CSV import."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SAEnum, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import ImportStatus

if TYPE_CHECKING:  # pragma: no cover
    from app.models.order import Order


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        # Named explicitly. An auto-generated constraint name is chosen by the
        # database and is awkward to reference from a later migration.
        UniqueConstraint("file_checksum", name="uq_import_batches_file_checksum"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)

    # Makes imports idempotent at the file level (§4): re-uploading the same
    # export is rejected by the database rather than double-counting revenue.
    file_checksum: Mapped[str] = mapped_column(String(64), nullable=False)

    row_count: Mapped[int] = mapped_column(nullable=False, default=0)

    # VARCHAR, not a native Postgres enum — see app/models/enums.py.
    status: Mapped[ImportStatus] = mapped_column(
        SAEnum(
            ImportStatus,
            native_enum=False,
            create_constraint=False,
            length=32,
            # Store the enum's VALUE ("pending"), not its NAME ("PENDING"),
            # which is SQLAlchemy's default.
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=ImportStatus.PENDING,
    )

    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)

    # passive_deletes="all" is REQUIRED for the RESTRICT on
    # orders.import_batch_id to take effect. Without it SQLAlchemy's default
    # behaviour is to UPDATE the children's foreign key to NULL before
    # deleting the parent — which silently defeats the database constraint and
    # lets an audit record be deleted out from under the orders it produced.
    # "all" tells the ORM to touch the children not at all and let PostgreSQL
    # decide.
    orders: Mapped[list["Order"]] = relationship(
        back_populates="import_batch", passive_deletes="all"
    )

    def __repr__(self) -> str:
        return f"<ImportBatch id={self.id} filename={self.filename!r} status={self.status}>"
