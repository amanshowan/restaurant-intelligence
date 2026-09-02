"""add line level discount to order items

Square's Items Detail export carries a `Discounts` value PER LINE. M2 parsed it
but did not persist it, so product-level discount had to be apportioned from the
order total — exact only for single-product orders. Measured against the first
real month, 70% of discount value (£535.91 of £767.31) sat on multi-product
orders where apportioning could misattribute it. This column stores what the
source actually said.

Backfill semantics — read this before trusting historical rows
--------------------------------------------------------------
The column is added with a server default of 0 purely so the NOT NULL
constraint can be applied to a table that already has rows. That default is
then DROPPED, so future inserts must state a value explicitly rather than
silently taking zero.

Rows written before this migration therefore hold 0, and **0 here means "not
captured", not "no discount was given"**. There is deliberately no backfill:
the only honest source for a line discount is the Square export it came from,
and order-level totals cannot be decomposed back into lines without inventing
the very apportionment this change removes. Any batch imported before this
migration must be deleted and re-imported to carry trustworthy line discounts.

Reviewed by hand after autogenerate: the server default is dropped after the
column is added, and the downgrade is a plain column drop (lossy, since the
per-line values cannot be reconstructed from what remains).

Revision ID: 4f359908b385
Revises: f4fdc42bb63b
Create Date: 2026-09-02 15:17:52.222714

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f359908b385'
down_revision: Union[str, Sequence[str], None] = 'f4fdc42bb63b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default makes the NOT NULL addition possible on a populated table.
    op.add_column(
        'order_items',
        sa.Column('discount_amount', sa.Integer(), nullable=False,
                  server_default='0'),
    )
    # Drop it again: a default would let a future INSERT omit the column and
    # record a zero discount it never verified. The application always supplies
    # the value it read from the source.
    op.alter_column('order_items', 'discount_amount', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('order_items', 'discount_amount')
