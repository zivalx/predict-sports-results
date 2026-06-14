"""add elo_applied flag to match

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0010'
down_revision: Union[str, None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('match', sa.Column('elo_applied', sa.Boolean(), nullable=False, server_default='0'))
    # Mark already-completed matches as applied (their Elo was processed by the catchup)
    op.execute("UPDATE match SET elo_applied = 1 WHERE status = 'FT' AND home_score IS NOT NULL AND away_score IS NOT NULL")


def downgrade() -> None:
    op.drop_column('match', 'elo_applied')
