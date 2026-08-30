"""Application-level enums for columns stored as VARCHAR.

ARCHITECTURE.md §3: `orders.channel` and `import_batches.status` are stored as
VARCHAR and validated in Python, not as native PostgreSQL enum types. Adding a
value to a native enum requires a migration; real ingestion is expected to turn
up new channels, and the schema should absorb that without one.

These are mapped with SQLAlchemy's Enum type configured as
`native_enum=False, create_constraint=False`, which yields a plain VARCHAR
column with NO database-level CHECK constraint — a CHECK would reintroduce the
exact migration-per-value problem we are avoiding. The attribute is still typed
as the enum in Python, so the application layer keeps full type safety.

Trade-off (§3): the guarantee lives in the application, so a process writing
directly to Postgres could insert an invalid value. Accepted because the
application is the sole writer.
"""

from enum import Enum


class Channel(str, Enum):
    """How an order reached the business.

    Inherits from `str` so the member compares equal to its value and
    serialises directly to JSON.
    """

    IN_STORE = "in_store"
    COLLECTION = "collection"
    DELIVERY = "delivery"


class ImportStatus(str, Enum):
    """Lifecycle of a CSV import.

    New values (e.g. "partial" for an import with row-level errors) can be
    added here without a database migration — that is the point of storing
    this as VARCHAR.
    """

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
