"""Nombre y apellidos obligatorios en lugar del nombre opcional.

Revision ID: 0005_first_and_last_name
Revises: 0004_user_name
Create Date: 2026-11-24
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0005_first_and_last_name"
down_revision: str | None = "0004_user_name"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("first_name", sa.String(100)), schema="auth")
    op.add_column("users", sa.Column("last_name", sa.String(100)), schema="auth")
    # Solo hay cuentas de desarrollo y de CI: el nombre anterior pasa a first_name y, si no
    # había, queda vacío. Las cuentas nuevas siempre traen los dos desde el registro.
    op.execute("UPDATE auth.users SET first_name = coalesce(name, ''), last_name = ''")
    op.alter_column("users", "first_name", nullable=False, schema="auth")
    op.alter_column("users", "last_name", nullable=False, schema="auth")
    op.drop_column("users", "name", schema="auth")


def downgrade() -> None:
    op.add_column("users", sa.Column("name", sa.String(100), nullable=True), schema="auth")
    # «Luis Miguel» + «Aguilar García» cabe en 100 caracteres solo si se recorta.
    op.execute(
        "UPDATE auth.users SET name = left(nullif(trim(first_name || ' ' || last_name), ''), 100)"
    )
    op.drop_column("users", "last_name", schema="auth")
    op.drop_column("users", "first_name", schema="auth")
