"""Add organization emitter fields for e-invoicing (EN 16931 / Factur-X)

Revision ID: c7a1e9d4b3f2
Revises: b02d2872cd47
Create Date: 2026-10-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7a1e9d4b3f2'
down_revision: Union[str, Sequence[str], None] = 'b02d2872cd47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('organizations') as batch_op:
        batch_op.add_column(sa.Column('siret', sa.String(length=14), nullable=True))
        batch_op.add_column(sa.Column('tax_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('address_line1', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('postal_code', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('city', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('country', sa.String(length=2), nullable=False, server_default='FR'))
        batch_op.add_column(sa.Column('email', sa.String(length=320), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('organizations') as batch_op:
        batch_op.drop_column('email')
        batch_op.drop_column('country')
        batch_op.drop_column('city')
        batch_op.drop_column('postal_code')
        batch_op.drop_column('address_line1')
        batch_op.drop_column('tax_id')
        batch_op.drop_column('siret')
