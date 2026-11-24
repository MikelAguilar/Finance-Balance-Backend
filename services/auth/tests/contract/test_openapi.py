"""Prueba de contrato: la API publicada debe coincidir con services/auth/openapi.json.

La app Android se programa contra ese archivo. Si un cambio altera la API sin querer, esta
prueba falla. Si el cambio es intencional, regenera el archivo y revísalo en el PR:
    UPDATE_OPENAPI=1 uv run pytest services/auth/tests/contract
"""

import json
import os
from pathlib import Path

from auth_service.config import Settings
from auth_service.main import create_app

from ..conftest import DATABASE_URL, JWT_SECRET

SNAPSHOT = Path(__file__).parents[2] / "openapi.json"


def current_spec() -> dict:
    settings = Settings(app_env="development", database_url=DATABASE_URL, jwt_secret=JWT_SECRET)
    return create_app(settings).openapi()


def test_la_api_coincide_con_el_contrato_publicado() -> None:
    spec = current_spec()
    if os.environ.get("UPDATE_OPENAPI"):
        SNAPSHOT.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    assert spec == json.loads(SNAPSHOT.read_text(encoding="utf-8")), (
        "La API cambió. Si es intencional, regenera el contrato: "
        "UPDATE_OPENAPI=1 uv run pytest services/auth/tests/contract"
    )
