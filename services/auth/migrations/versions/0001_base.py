"""Revisión base sin tablas; las tablas llegan en B1.

Revision ID: 0001_base
Revises:
Create Date: 2026-11-21

"""

from collections.abc import Sequence

revision: str = "0001_base"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
