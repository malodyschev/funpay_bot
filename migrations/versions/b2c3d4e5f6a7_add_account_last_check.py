"""add accounts.last_check

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-17

"""
import sqlalchemy as sa
from alembic import op


revision: str = 'b2c3d4e5f6a7'
down_revision: str | None = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('accounts', sa.Column('last_check', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('accounts', 'last_check')
