"""add lots.is_autodelivery

Revision ID: a1b2c3d4e5f6
Revises: 5888c6c6f234
Create Date: 2026-06-17

"""
import sqlalchemy as sa
from alembic import op


revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = '5888c6c6f234'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'lots',
        sa.Column('is_autodelivery', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('lots', 'is_autodelivery')
