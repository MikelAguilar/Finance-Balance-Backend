"""Número de cambio: el cursor de la descarga por páginas.

Cada escritura en cards, movements o monthly_income toma el siguiente número de una secuencia que
comparten las tres tablas. La app guarda el último que recibió y pide lo que cambió después.

Revision ID: 0005_change_seq
Revises: 0004_monthly_income
Create Date: 2026-11-26
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0005_change_seq"
down_revision: str | None = "0004_monthly_income"
branch_labels: str | None = None
depends_on: str | None = None

TABLES = ("cards", "movements", "monthly_income")


def upgrade() -> None:
    op.execute("CREATE SEQUENCE finance.change_seq")
    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                "change_seq",
                sa.BigInteger(),
                server_default=sa.text("nextval('finance.change_seq')"),
                nullable=False,
            ),
            schema="finance",
        )
        op.create_index(
            f"ix_{table}_user_change_seq", table, ["user_id", "change_seq"], schema="finance"
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_index(f"ix_{table}_user_change_seq", table_name=table, schema="finance")
        op.drop_column(table, "change_seq", schema="finance")
    op.execute("DROP SEQUENCE finance.change_seq")
