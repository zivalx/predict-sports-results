"""predicted score fields on match_forecast

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('match_forecast', sa.Column('predicted_score', sa.String(), nullable=True))
    op.add_column('match_forecast', sa.Column('predicted_score_prob', sa.Float(), nullable=True))
    op.add_column('match_forecast', sa.Column('expected_goals', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('match_forecast', 'expected_goals')
    op.drop_column('match_forecast', 'predicted_score_prob')
    op.drop_column('match_forecast', 'predicted_score')
