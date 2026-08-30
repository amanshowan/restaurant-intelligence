"""initial schema

Creates the canonical vendor-neutral schema (ARCHITECTURE.md §4): products,
orders, order_items and import_batches.

Reviewed by hand after autogenerate. One change was made to the generated
output: create_constraint=False is stated explicitly on both sa.Enum columns.
It is SQLAlchemy's current default, but a migration must reproduce the same
schema years from now regardless of library defaults. These columns are
VARCHAR with no CHECK constraint by design (§3) — a CHECK would reintroduce
the migration-per-enum-value problem that storing them as VARCHAR avoids.

Revision ID: c52565f1e614
Revises: 
Create Date: 2026-08-30 23:03:24.920465

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c52565f1e614'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('import_batches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('file_checksum', sa.String(length=64), nullable=False),
    sa.Column('row_count', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('pending', 'processing', 'completed', 'failed', name='importstatus',
              native_enum=False, create_constraint=False, length=32), nullable=False),
    sa.Column('imported_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('error_log', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('file_checksum', name='uq_import_batches_file_checksum')
    )
    op.create_table('products',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('category', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_products_category'), 'products', ['category'], unique=False)
    op.create_index(op.f('ix_products_name'), 'products', ['name'], unique=False)
    op.create_table('orders',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=50), nullable=False),
    sa.Column('source_order_id', sa.String(length=255), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('channel', sa.Enum('in_store', 'collection', 'delivery', name='channel',
              native_enum=False, create_constraint=False, length=32), nullable=False),
    sa.Column('gross_amount', sa.Integer(), nullable=False),
    sa.Column('discount_amount', sa.Integer(), nullable=False),
    sa.Column('net_amount', sa.Integer(), nullable=False),
    sa.Column('item_count', sa.Integer(), nullable=False),
    sa.Column('import_batch_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['import_batch_id'], ['import_batches.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'source_order_id', name='uq_orders_source_order')
    )
    op.create_index(op.f('ix_orders_import_batch_id'), 'orders', ['import_batch_id'], unique=False)
    op.create_index(op.f('ix_orders_occurred_at'), 'orders', ['occurred_at'], unique=False)
    op.create_table('order_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('order_id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('unit_price', sa.Integer(), nullable=False),
    sa.Column('line_total', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_order_items_order_id'), 'order_items', ['order_id'], unique=False)
    op.create_index(op.f('ix_order_items_product_id'), 'order_items', ['product_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_order_items_product_id'), table_name='order_items')
    op.drop_index(op.f('ix_order_items_order_id'), table_name='order_items')
    op.drop_table('order_items')
    op.drop_index(op.f('ix_orders_occurred_at'), table_name='orders')
    op.drop_index(op.f('ix_orders_import_batch_id'), table_name='orders')
    op.drop_table('orders')
    op.drop_index(op.f('ix_products_name'), table_name='products')
    op.drop_index(op.f('ix_products_category'), table_name='products')
    op.drop_table('products')
    op.drop_table('import_batches')
