"""One physical file within an import batch."""

from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import ImportFileRole

if TYPE_CHECKING:  # pragma: no cover
    from app.models.import_batch import ImportBatch


class ImportFile(Base):
    """Identity, idempotency and row accounting for a single export file.

    Splitting this out of ImportBatch separates two different concerns that
    were previously conflated: idempotency is a property of a FILE, while
    reconciliation is a property of the BATCH.
    """

    __tablename__ = "import_files"
    __table_args__ = (
        # File-level idempotency (§4). Re-submitting a file already ingested is
        # rejected by the database, even inside a new batch, so revenue cannot
        # be double-counted. The importer preflights every supplied checksum
        # against this constraint BEFORE creating a batch or touching sales
        # data, so a partial import cannot leave an orphaned batch behind.
        UniqueConstraint("file_checksum", name="uq_import_files_file_checksum"),
        # A batch holds at most one file per role.
        UniqueConstraint(
            "import_batch_id", "role", name="uq_import_files_batch_role"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    import_batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # VARCHAR, not a native Postgres enum — see app/models/enums.py.
    role: Mapped[ImportFileRole] = mapped_column(
        SAEnum(
            ImportFileRole,
            native_enum=False,
            create_constraint=False,
            length=32,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_checksum: Mapped[str] = mapped_column(String(64), nullable=False)

    # Row accounting. Zero-value transactions are excluded from analytical
    # orders, but the exclusion is COUNTED here rather than silently dropped;
    # reasons go in ImportBatch.error_log.
    row_count: Mapped[int] = mapped_column(nullable=False, default=0)
    rows_imported: Mapped[int] = mapped_column(nullable=False, default=0)
    rows_skipped: Mapped[int] = mapped_column(nullable=False, default=0)

    import_batch: Mapped["ImportBatch"] = relationship(back_populates="files")

    def __repr__(self) -> str:
        return f"<ImportFile id={self.id} role={self.role} filename={self.filename!r}>"
