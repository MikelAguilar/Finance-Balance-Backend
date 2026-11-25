"""Movimientos: cargos normales, compras a meses y pagos de la tarjeta.

Revision ID: 0003_movements
Revises: 0002_cards
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0003_movements"
down_revision: str | None = "0002_cards"
branch_labels: str | None = None
depends_on: str | None = None

KIND_RULE = """
(kind = 'normal' AND months IS NULL AND monthly_rate IS NULL AND payment_source IS NULL)
OR (kind = 'installment' AND months IS NOT NULL AND monthly_rate IS NOT NULL
    AND months BETWEEN 1 AND 120 AND monthly_rate >= 0 AND monthly_rate < 1
    AND payment_source IS NULL)
OR (kind = 'payment' AND months IS NULL AND monthly_rate IS NULL
    AND payment_source IS NOT NULL AND payment_source IN ('debit', 'cash'))
"""


def upgrade() -> None:
    # Un movimiento solo puede apuntar a una tarjeta de su misma cuenta.
    op.create_unique_constraint("uq_cards_id_user", "cards", ["id", "user_id"], schema="finance")
    op.create_table(
        "movements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("server_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurred_offset_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("kind", sa.String(11), nullable=False),
        sa.Column("months", sa.SmallInteger(), nullable=True),
        sa.Column("monthly_rate", sa.Numeric(7, 6), nullable=True),
        sa.Column("payment_source", sa.String(5), nullable=True),
        sa.Column("review_status", sa.String(14), nullable=False),
        sa.Column("owner_cut", sa.Date(), nullable=False),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_movements_user_idempotency_key"),
        sa.ForeignKeyConstraint(
            ["card_id", "user_id"],
            ["finance.cards.id", "finance.cards.user_id"],
            name="fk_movements_card",
        ),
        sa.CheckConstraint("version >= 1", name="ck_movements_version"),
        sa.CheckConstraint("amount_cents > 0", name="ck_movements_amount"),
        sa.CheckConstraint(
            "occurred_offset_minutes BETWEEN -720 AND 840", name="ck_movements_occurred_offset"
        ),
        sa.CheckConstraint(KIND_RULE, name="ck_movements_kind"),
        sa.CheckConstraint(
            "review_status IN ('pending_review', 'confirmed')", name="ck_movements_review_status"
        ),
        schema="finance",
    )


def downgrade() -> None:
    op.drop_table("movements", schema="finance")
    op.drop_constraint("uq_cards_id_user", "cards", schema="finance")
