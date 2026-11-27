"""Los ejemplos de subida compartidos con la app (contract/sync-examples.json) son lo que contesta
el servidor. Corren en orden sobre una misma cuenta, con reloj fijo e ids predecibles."""

import json
from datetime import datetime
from itertools import count
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from finance_service.application.sync import Sync
from finance_service.config import Settings
from finance_service.infrastructure.repositories import sql_store
from finance_service.main import create_app

CONTRACT = json.loads(
    (Path(__file__).parents[2] / "contract" / "sync-examples.json").read_text(encoding="utf-8")
)
NOW = datetime.fromisoformat(CONTRACT["upload"]["now"])
USER = CONTRACT["upload"]["user_id"]


def server_ids():
    """Los ids que asigna el servidor, en orden: …0101, …0102, …"""
    return (UUID(f"00000000-0000-4000-8000-{number:012d}") for number in count(101))


def test_the_upload_examples_are_what_the_server_answers(engine, database_url, numbers_from_one):
    ids = server_ids()
    with TestClient(create_app(Settings(database_url=database_url))) as client:
        store = sql_store(sessionmaker(engine), new_id=lambda: next(ids))
        client.app.state.sync = Sync(store, clock=lambda: NOW)
        for example in CONTRACT["upload"]["examples"]:
            response = client.post("/sync", json=example["request"], headers={"X-User-Id": USER})
            answer = {"status": response.status_code, "response": response.json()}
            assert answer == {"status": example["status"], "response": example["response"]}, (
                example["name"]
            )
