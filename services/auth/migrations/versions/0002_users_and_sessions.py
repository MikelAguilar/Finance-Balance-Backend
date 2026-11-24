"""Usuarios y sesiones por dispositivo, en el esquema auth.

Revision ID: 0002_users_and_sessions
Revises: 0001_base
Create Date: 2026-11-24
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0002_users_and_sessions"
down_revision: str | None = "0001_base"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
        schema="auth",
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("device_id", sa.String(100), nullable=False),
        sa.Column("device_name", sa.String(100), nullable=False),
        sa.Column("refresh_token_hash", sa.CHAR(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("refresh_token_hash", name="uq_sessions_refresh_token_hash"),
        schema="auth",
    )
    op.create_index("ix_auth_sessions_user_id", "sessions", ["user_id"], schema="auth")
    op.create_index(
        "uq_sessions_user_device_unrevoked",
        "sessions",
        ["user_id", "device_id"],
        unique=True,
        schema="auth",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("sessions", schema="auth")
    op.drop_table("users", schema="auth")
    op.execute("DROP SCHEMA IF EXISTS auth")
