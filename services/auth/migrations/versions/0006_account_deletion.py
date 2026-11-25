"""Borrado lógico de cuentas: users.deleted_at y correo único solo entre cuentas activas.

Revision ID: 0006_account_deletion
Revises: 0005_first_and_last_name
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0006_account_deletion"
down_revision: str | None = "0005_first_and_last_name"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True), schema="auth"
    )
    # La restricción única pasa a ser un índice único parcial con el mismo nombre: el código que
    # traduce el choque de correos a EmailAlreadyRegistered busca «uq_users_email».
    op.drop_constraint("uq_users_email", "users", schema="auth", type_="unique")
    op.create_index(
        "uq_users_email",
        "users",
        ["email"],
        unique=True,
        schema="auth",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    # Nada se borra nunca. Sin deleted_at, una cuenta eliminada volvería a estar activa (y su
    # correo podría chocar con una cuenta nueva): si existe alguna, la bajada se detiene.
    deleted = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM auth.users WHERE deleted_at IS NOT NULL")
    )
    if deleted:
        raise RuntimeError(
            f"No se puede bajar la migración 0006: hay {deleted} cuentas eliminadas que "
            "volverían a quedar activas."
        )
    op.drop_index("uq_users_email", "users", schema="auth")
    op.create_unique_constraint("uq_users_email", "users", ["email"], schema="auth")
    op.drop_column("users", "deleted_at", schema="auth")
