"""square dataset schema evolution

Schema changes required by the first real Square export (see ARCHITECTURE.md §4):

  * import_files split out of import_batches — idempotency is a property of a
    FILE, reconciliation is a property of the BATCH.
  * import_batches gains label, period_start, period_end: filenames proved an
    unreliable statement of actual data coverage. The period bounds are DATE
    and inclusive — calendar coverage, not instants; Order.occurred_at remains
    TIMESTAMPTZ because it IS an instant.
  * products gains variation (the catalogue grain is name+variation) and kind
    (gift vouchers are ingested but excluded from operating revenue).
  * orders gains event_type (refunds must not inflate order counts) and
    source_payment_id (the only link from a refund to the payment it reverses).

The new Channel value "mixed" required NO migration — the column is VARCHAR
with no CHECK constraint by design (§3).

Reviewed by hand after autogenerate. Two changes were made to the generated
output:

  1. create_constraint=False stated explicitly on all three sa.Enum columns,
     so these stay VARCHAR regardless of future library defaults.
  2. The generated downgrade() re-added filename/file_checksum/row_count as
     NOT NULL with no server default, which fails on any table that already
     has rows. Server defaults were added so the downgrade is applicable.
     Note it remains structurally reversible but LOSSY: import_files is
     dropped, and the per-file detail it held cannot be reconstructed.

Revision ID: f4fdc42bb63b
Revises: c52565f1e614
Create Date: 2026-09-01 19:19:16.866362

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4fdc42bb63b'
down_revision: Union[str, Sequence[str], None] = 'c52565f1e614'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('import_files',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('import_batch_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.Enum('transactions', 'items_detail', 'items_summary', name='importfilerole',
                       native_enum=False, create_constraint=False, length=32), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('file_checksum', sa.String(length=64), nullable=False),
    sa.Column('row_count', sa.Integer(), nullable=False),
    sa.Column('rows_imported', sa.Integer(), nullable=False),
    sa.Column('rows_skipped', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['import_batch_id'], ['import_batches.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('file_checksum', name='uq_import_files_file_checksum'),
    sa.UniqueConstraint('import_batch_id', 'role', name='uq_import_files_batch_role')
    )
    op.create_index(op.f('ix_import_files_import_batch_id'), 'import_files', ['import_batch_id'], unique=False)
    op.add_column('import_batches', sa.Column('label', sa.String(length=255), nullable=True))
    op.add_column('import_batches', sa.Column('period_start', sa.Date(), nullable=True))
    op.add_column('import_batches', sa.Column('period_end', sa.Date(), nullable=True))
    op.drop_constraint(op.f('uq_import_batches_file_checksum'), 'import_batches', type_='unique')
    op.drop_column('import_batches', 'filename')
    op.drop_column('import_batches', 'row_count')
    op.drop_column('import_batches', 'file_checksum')
    op.add_column('orders', sa.Column('event_type', sa.Enum('payment', 'refund', name='ordereventtype',
                       native_enum=False, create_constraint=False, length=32), server_default='payment', nullable=False))
    op.add_column('orders', sa.Column('source_payment_id', sa.String(length=255), nullable=True))
    op.create_index('ix_orders_source_payment_id', 'orders', ['source', 'source_payment_id'], unique=False)
    op.add_column('products', sa.Column('variation', sa.String(length=100), server_default='', nullable=False))
    op.add_column('products', sa.Column('kind', sa.Enum('menu_item', 'gift_voucher', 'custom_amount', name='productkind',
                       native_enum=False, create_constraint=False, length=32), server_default='menu_item', nullable=False))
    op.create_unique_constraint('uq_products_name_variation', 'products', ['name', 'variation'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_products_name_variation', 'products', type_='unique')
    op.drop_column('products', 'kind')
    op.drop_column('products', 'variation')
    op.drop_index('ix_orders_source_payment_id', table_name='orders')
    op.drop_column('orders', 'source_payment_id')
    op.drop_column('orders', 'event_type')
    op.add_column('import_batches', sa.Column('file_checksum', sa.VARCHAR(length=64), server_default='', autoincrement=False, nullable=False))
    op.add_column('import_batches', sa.Column('row_count', sa.INTEGER(), server_default='0', autoincrement=False, nullable=False))
    op.add_column('import_batches', sa.Column('filename', sa.VARCHAR(length=255), server_default='', autoincrement=False, nullable=False))
    op.create_unique_constraint(op.f('uq_import_batches_file_checksum'), 'import_batches', ['file_checksum'], postgresql_nulls_not_distinct=False)
    op.drop_column('import_batches', 'period_end')
    op.drop_column('import_batches', 'period_start')
    op.drop_column('import_batches', 'label')
    op.drop_index(op.f('ix_import_files_import_batch_id'), table_name='import_files')
    op.drop_table('import_files')
