"""Último cambio aplicado: reintentar una subida nunca aplica dos veces la misma edición.

Revision ID: 0006_last_change_id
Revises: 0005_change_seq
Create Date: 2026-11-26
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0006_last_change_id"
down_revision: str | None = "0005_change_seq"
branch_labels: str | None = None
depends_on: str | None = None

TABLES = ("cards", "movements", "monthly_income")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table, sa.Column("last_change_id", sa.Uuid(), nullable=True), schema="finance"
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "last_change_id", schema="finance")
