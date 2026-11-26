"""Tarjetas, con las reglas de entrada repetidas como CHECK de respaldo.

Revision ID: 0002_cards
Revises: 0001_base
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0002_cards"
down_revision: str | None = "0001_base"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "cards",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("server_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("cut_day", sa.SmallInteger(), nullable=False),
        sa.Column("personal_limit_cents", sa.BigInteger(), nullable=True),
        sa.Column("bank_limit_cents", sa.BigInteger(), nullable=True),
        sa.Column("used_at_creation_cents", sa.BigInteger(), nullable=False),
        sa.Column("installments_count_against_limit", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_cards_user_idempotency_key"),
        sa.CheckConstraint("version >= 1", name="ck_cards_version"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_cards_name"),
        sa.CheckConstraint("cut_day BETWEEN 1 AND 31", name="ck_cards_cut_day"),
        sa.CheckConstraint("personal_limit_cents > 0", name="ck_cards_personal_limit"),
        sa.CheckConstraint("bank_limit_cents > 0", name="ck_cards_bank_limit"),
        sa.CheckConstraint(
            "personal_limit_cents IS NOT NULL OR bank_limit_cents IS NOT NULL",
            name="ck_cards_at_least_one_limit",
        ),
        sa.CheckConstraint("used_at_creation_cents >= 0", name="ck_cards_used_at_creation"),
        schema="finance",
    )


def downgrade() -> None:
    op.drop_table("cards", schema="finance")
