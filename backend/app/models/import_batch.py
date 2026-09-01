"""A logical import: one extraction period's worth of Square exports."""

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Enum as SAEnum, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import ImportStatus

if TYPE_CHECKING:  # pragma: no cover
    from app.models.import_file import ImportFile
    from app.models.order import Order


class ImportBatch(Base):
    """One logical import, spanning several physical files.

    A Square monthly import is Transactions + Items Detail + an optional Items
    Summary. The batch is the reconciliation unit; per-file identity and
    idempotency live on ImportFile.
    """

    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Human-readable identity for the batch, e.g. "august-2026". The files
    # carry the machine identity; this is for humans reading a list of imports.
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Actual data coverage, derived from parsed rows — NOT from filenames. The
    # first real export proved filenames unreliable: the Items Summary was
    # named ...2026-09-02 while covering the same 1-31 August as its siblings.
    # The batch states its own coverage explicitly.
    #
    # DATE, not TIMESTAMPTZ, and INCLUSIVE at both ends: this is calendar
    # coverage ("1-31 August"), not an instant in time. A period has no
    # meaningful moment or offset, so giving it one would invite false
    # precision and pointless timezone conversion. Contrast Order.occurred_at,
    # which IS an instant and stays TIMESTAMPTZ.
    #
    # These are business-local (Europe/London) calendar dates, taken from the
    # export's own date column rather than from UTC-converted timestamps. An
    # order at 00:30 on 1 August BST is 23:30 on 31 July UTC; deriving bounds
    # from UTC instants would silently report coverage starting a day early.
    #
    # To select the orders belonging to a period, use a HALF-OPEN interval
    # whose boundaries are interpreted in Europe/London and then converted to
    # UTC (see ARCHITECTURE.md §4):
    #
    #     occurred_at >= local_midnight(period_start)
    #     occurred_at <  local_midnight(period_end + 1 day)
    #
    # Do not compare occurred_at <= period_end: the date coerces to midnight
    # and silently drops almost all of the final day. Do not apply a constant
    # UTC offset either — 1-31 Aug 2026 spans BST (>= 2026-07-31 23:00Z,
    # < 2026-08-31 23:00Z) while 1-31 Jan 2026 spans GMT (>= 2026-01-01 00:00Z,
    # < 2026-02-01 00:00Z), and an October range straddles the switch so its
    # two boundaries have different offsets.
    #
    # Nullable because coverage is only known after the files are parsed,
    # which happens after the batch row exists.
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    # VARCHAR, not a native Postgres enum — see app/models/enums.py.
    status: Mapped[ImportStatus] = mapped_column(
        SAEnum(
            ImportStatus,
            native_enum=False,
            create_constraint=False,
            length=32,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=ImportStatus.PENDING,
    )

    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)

    # CASCADE: a file record has no meaning without its batch.
    files: Mapped[list["ImportFile"]] = relationship(
        back_populates="import_batch",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # RESTRICT (see Order.import_batch_id): passive_deletes="all" stops the ORM
    # nulling out the children's FK and defeating the database constraint.
    orders: Mapped[list["Order"]] = relationship(
        back_populates="import_batch", passive_deletes="all"
    )

    def __repr__(self) -> str:
        return f"<ImportBatch id={self.id} label={self.label!r} status={self.status}>"
