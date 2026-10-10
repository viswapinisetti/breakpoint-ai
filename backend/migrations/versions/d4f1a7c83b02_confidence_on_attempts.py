"""Confidence calibration: record how sure the student was when judging

Revision ID: d4f1a7c83b02
Revises: c9a41d70f2b1
Create Date: 2026-09-13 00:00:00.000000

One additive, nullable column. Existing attempts stay null, which is the
truthful reading: those students were never asked. Calibration skips them
rather than assuming a 50.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4f1a7c83b02'
down_revision: Union[str, Sequence[str], None] = 'c9a41d70f2b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('attempts') as batch:
        batch.add_column(sa.Column('confidence', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('attempts') as batch:
        batch.drop_column('confidence')
