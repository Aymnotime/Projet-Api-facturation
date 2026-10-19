"""add webhook_deliveries.error_message + statut dead-letter

Revision ID: d3f8a1c2b5e9
Revises: c7a1e9d4b3f2
Create Date: 2026-10-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd3f8a1c2b5e9'
down_revision: Union[str, Sequence[str], None] = 'c7a1e9d4b3f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "webhook_deliveries",
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_webhook_deliveries_status",
        "webhook_deliveries",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_status", table_name="webhook_deliveries")
    op.drop_column("webhook_deliveries", "error_message")
