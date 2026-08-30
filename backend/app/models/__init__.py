"""SQLAlchemy models.

Every model is imported here so that importing `app.models` registers all
mappers with the declarative Base. Alembic's autogenerate (commit 5) relies on
this: a model that is never imported is invisible to it, and would be silently
omitted from — or dropped by — a generated migration.
"""

from app.models.enums import Channel, ImportStatus
from app.models.import_batch import ImportBatch
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product

__all__ = [
    "Channel",
    "ImportStatus",
    "ImportBatch",
    "Order",
    "OrderItem",
    "Product",
]
