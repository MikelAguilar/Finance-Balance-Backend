"""Rotación del refresh token y registro de intentos fallidos de inicio de sesión.

Revision ID: 0003_refresh_and_attempts
Revises: 0002_users_and_sessions
Create Date: 2026-11-24
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0003_refresh_and_attempts"
down_revision: str | None = "0002_users_and_sessions"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("previous_refresh_token_hash", sa.CHAR(64), nullable=True),
        schema="auth",
    )
    op.create_index(
        "ix_auth_sessions_previous_refresh_token_hash",
        "sessions",
        ["previous_refresh_token_hash"],
        schema="auth",
    )
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        schema="auth",
    )
    op.create_index(
        "ix_auth_login_attempts_email_attempted_at",
        "login_attempts",
        ["email", "attempted_at"],
        schema="auth",
    )


def downgrade() -> None:
    op.drop_table("login_attempts", schema="auth")
    op.drop_index(
        "ix_auth_sessions_previous_refresh_token_hash", table_name="sessions", schema="auth"
    )
    op.drop_column("sessions", "previous_refresh_token_hash", schema="auth")
