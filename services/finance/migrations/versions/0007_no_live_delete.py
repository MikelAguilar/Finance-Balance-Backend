"""Nada vivo se borra: un DELETE de una fila sin deleted_at falla en la base.

La API nunca borra filas (borrar es marcar deleted_at). Solo la limpieza manual que hace Luis
después de un respaldo elimina filas, y únicamente las ya marcadas: un error o un script
equivocado no puede llevarse datos vivos. TRUNCATE (lo que usan las pruebas) no dispara el
trigger.

Revision ID: 0007_no_live_delete
Revises: 0006_last_change_id
Create Date: 2026-11-27
"""

from alembic import op

revision: str = "0007_no_live_delete"
down_revision: str | None = "0006_last_change_id"
branch_labels: str | None = None
depends_on: str | None = None

TABLES = ("cards", "movements", "monthly_income")


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION finance.reject_live_delete() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.deleted_at IS NULL THEN
                RAISE EXCEPTION 'finance.%: solo se eliminan filas con deleted_at', TG_TABLE_NAME;
            END IF;
            RETURN OLD;
        END;
        $$
        """
    )
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER no_live_delete BEFORE DELETE ON finance.{table} "
            "FOR EACH ROW EXECUTE FUNCTION finance.reject_live_delete()"
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TRIGGER no_live_delete ON finance.{table}")
    op.execute("DROP FUNCTION finance.reject_live_delete()")
