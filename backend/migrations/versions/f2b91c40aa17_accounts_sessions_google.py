"""Accounts mode: email/password and Google sign-in, with server-side sessions

Revision ID: f2b91c40aa17
Revises: d4f1a7c83b02
Create Date: 2026-09-13 00:00:00.000000

Additive. Existing students keep their `external_id` and gain null account
columns, which reads correctly: they arrived by header or SSO and have no
password. `login_email` and `google_sub` are nullable-unique rather than
empty-string-unique, so every one of those rows can coexist.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f2b91c40aa17'
down_revision: Union[str, Sequence[str], None] = 'd4f1a7c83b02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('login_email', sa.String(length=320), nullable=True))
        batch.add_column(
            sa.Column(
                'password_hash', sa.String(length=256), nullable=False, server_default=''
            )
        )
        batch.add_column(sa.Column('google_sub', sa.String(length=128), nullable=True))
        batch.add_column(
            sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_index('ix_users_login_email', ['login_email'], unique=True)
        batch.create_index('ix_users_google_sub', ['google_sub'], unique=True)

    op.create_table(
        'login_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('user_agent', sa.String(length=200), nullable=False, server_default=''),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_login_sessions_user_id', 'login_sessions', ['user_id'])
    op.create_index(
        'ix_login_sessions_token_hash', 'login_sessions', ['token_hash'], unique=True
    )

    op.create_table(
        'oauth_handshakes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(length=64), nullable=False),
        sa.Column('nonce', sa.String(length=64), nullable=False),
        sa.Column('code_verifier', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_oauth_handshakes_state', 'oauth_handshakes', ['state'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_oauth_handshakes_state', table_name='oauth_handshakes')
    op.drop_table('oauth_handshakes')
    op.drop_index('ix_login_sessions_token_hash', table_name='login_sessions')
    op.drop_index('ix_login_sessions_user_id', table_name='login_sessions')
    op.drop_table('login_sessions')
    with op.batch_alter_table('users') as batch:
        batch.drop_index('ix_users_google_sub')
        batch.drop_index('ix_users_login_email')
        batch.drop_column('last_login_at')
        batch.drop_column('google_sub')
        batch.drop_column('password_hash')
        batch.drop_column('login_email')
