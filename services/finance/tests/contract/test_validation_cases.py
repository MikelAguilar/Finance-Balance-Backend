"""El servidor cumple los casos compartidos con la app (contract/validation-cases.json)."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from finance_service.domain.errors import InvalidField
from finance_service.domain.model import parse_card, parse_monthly_income, parse_movement

CASES_FILE = Path(__file__).parents[2] / "contract" / "validation-cases.json"
CONTRACT = json.loads(CASES_FILE.read_text(encoding="utf-8"))
NOW = datetime.fromisoformat(CONTRACT["now"])
PARSERS = {
    "card": parse_card,
    "movement": lambda data: parse_movement(data, NOW),
    "monthly_income": parse_monthly_income,
}


@pytest.mark.parametrize("case", CONTRACT["cases"], ids=lambda case: case["name"])
def test_the_server_accepts_and_rejects_like_the_contract_says(case: dict) -> None:
    parse = PARSERS[case["entity"]]
    if case["error"] is None:
        parse(case["input"])
        return
    with pytest.raises(InvalidField) as error:
        parse(case["input"])
    assert {"field": error.value.field, "rule": error.value.rule} == case["error"]


def test_every_rule_is_described_and_exercised() -> None:
    used = {case["error"]["rule"] for case in CONTRACT["cases"] if case["error"]}
    assert used == set(CONTRACT["rules"])


def test_case_names_are_unique() -> None:
    names = [case["name"] for case in CONTRACT["cases"]]
    assert len(names) == len(set(names))
