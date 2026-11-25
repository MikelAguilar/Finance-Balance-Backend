from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

SCHEMA = "finance"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


def include_finance_schema(name: str | None, type_: str, parent_names: dict) -> bool:
    """Filtro para Alembic: este servicio solo administra su propio esquema."""
    return name == SCHEMA if type_ == "schema" else True
