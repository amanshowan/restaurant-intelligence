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
    # Added after the first real Square export: 71 orders carried a combined
    # "Eat in, Takeaway" dining option. Adding this member required NO database
    # migration — the §3 varchar decision paying for itself within a week.
    MIXED = "mixed"
    # Ordered through Square Online with no fulfilment evidence in the export.
    # Deliberately NOT folded into collection or delivery: the export does not
    # say which, and guessing would put revenue in the wrong channel-mix bucket.
    ONLINE = "online"
    # A financial event whose channel genuinely cannot be established — in
    # practice a refund whose original payment falls outside the extraction
    # window. Preferred to dropping the record: losing money from the ledger is
    # worse than admitting one field is unknown.
    UNKNOWN = "unknown"


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


class OrderEventType(str, Enum):
    """Whether an order row is a sale or a refund.

    Square emits refunds as separate rows with their own Transaction ID and a
    negative amount. Storing them as orders keeps revenue arithmetic correct
    (sums include the negative), while this discriminator keeps order COUNTS
    correct — every count and average filters on PAYMENT.
    """

    PAYMENT = "payment"
    REFUND = "refund"


class ProductKind(str, Enum):
    """What a catalogue entry represents commercially.

    Not everything sold through the till is operating revenue. Gift vouchers
    are a liability at issuance and become revenue on redemption; counting
    them as menu sales inflates the month and double-counts later. They are
    still ingested so reconciliation against Square's own totals stays exact —
    this field is how analytics excludes them.
    """

    MENU_ITEM = "menu_item"
    GIFT_VOUCHER = "gift_voucher"
    # Square's open-price "Custom Amount" line: real revenue, no catalogue item.
    CUSTOM_AMOUNT = "custom_amount"


class ImportFileRole(str, Enum):
    """Which Square export a file within an import batch is.

    A logical monthly import is Transactions + Items Detail + an optional
    Items Summary. ITEMS_SUMMARY is reconciliation-only and never populates
    canonical sales tables.
    """

    TRANSACTIONS = "transactions"
    ITEMS_DETAIL = "items_detail"
    ITEMS_SUMMARY = "items_summary"
