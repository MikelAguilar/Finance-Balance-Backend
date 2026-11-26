"""Ingreso mensual: uno vigente por cuenta.

Revision ID: 0004_monthly_income
Revises: 0003_movements
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0004_monthly_income"
down_revision: str | None = "0003_movements"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "monthly_income",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("server_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint(
            "user_id", "idempotency_key", name="uq_monthly_income_user_idempotency_key"
        ),
        sa.CheckConstraint("version >= 1", name="ck_monthly_income_version"),
        sa.CheckConstraint("amount_cents > 0", name="ck_monthly_income_amount"),
        schema="finance",
    )
    op.create_index(
        "uq_monthly_income_user_current",
        "monthly_income",
        ["user_id"],
        unique=True,
        schema="finance",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("monthly_income", schema="finance")
