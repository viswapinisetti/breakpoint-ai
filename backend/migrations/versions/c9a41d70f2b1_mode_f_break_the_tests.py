"""Mode F: record the student's Break-the-Tests input on the attempt

Revision ID: c9a41d70f2b1
Revises: b62f62611556
Create Date: 2026-09-07 00:00:00.000000

Three additive, non-null-with-default columns. Existing attempts read as
"no test submitted", which is exactly right - they were not Mode F attempts.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c9a41d70f2b1'
down_revision: Union[str, Sequence[str], None] = 'b62f62611556'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('attempts') as batch:
        batch.add_column(
            sa.Column('test_input', sa.Text(), nullable=False, server_default='')
        )
        batch.add_column(
            sa.Column('test_submissions', sa.Integer(), nullable=False, server_default='0')
        )
        batch.add_column(
            sa.Column('test_broke_suite', sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('attempts') as batch:
        batch.drop_column('test_broke_suite')
        batch.drop_column('test_submissions')
        batch.drop_column('test_input')
