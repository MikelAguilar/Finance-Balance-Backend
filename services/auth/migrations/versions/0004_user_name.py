"""Nombre para mostrar en el perfil del usuario.

Revision ID: 0004_user_name
Revises: 0003_refresh_and_attempts
Create Date: 2026-11-24
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0004_user_name"
down_revision: str | None = "0003_refresh_and_attempts"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("name", sa.String(100), nullable=True), schema="auth")


def downgrade() -> None:
    op.drop_column("users", "name", schema="auth")
