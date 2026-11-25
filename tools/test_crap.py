import json

import pytest
from crap import crap, main, scores

SOURCE = """
def simple():
    return 1


def branchy(value):
    if value > 1:
        return "a"
    if value < 0:
        return "b"
    return "c"


class Thing:
    def method(self, value):
        return value or 0


def outer():
    def inner(flag):
        return 1 if flag else 2

    return inner
"""


@pytest.mark.parametrize(
    ("complexity", "covered", "expected"),
    [
        (6, 100.0, 6.0),  # LogIn.execute, hecho a mano: 6² × 0³ + 6
        (1, 0.0, 2.0),  # 1² × 1³ + 1
        (5, 50.0, 8.125),  # 25 × 0.125 + 5
        (10, 100.0, 10.0),
    ],
)
def test_crap_formula(complexity, covered, expected) -> None:
    assert crap(complexity, covered) == pytest.approx(expected)


def _coverage(path, functions):
    return {
        "files": {
            path: {
                "functions": {
                    name: {"start_line": line, "summary": {"percent_covered": percent}}
                    for name, (line, percent) in functions.items()
                }
            }
        }
    }


def test_scores_match_functions_by_start_line_including_methods_and_closures(tmp_path) -> None:
    module = tmp_path / "module.py"
    module.write_text(SOURCE, encoding="utf-8")
    report = _coverage(
        str(module),
        {
            "simple": (2, 100.0),
            "branchy": (6, 0.0),
            "Thing.method": (15, 100.0),
            "outer": (19, 100.0),
            "outer.inner": (20, 0.0),
        },
    )

    result = {name: score for name, _, score in scores(report)}

    assert result == {
        "simple": pytest.approx(1.0),
        "branchy": pytest.approx(3**2 + 3),
        "Thing.method": pytest.approx(2.0),
        "outer": pytest.approx(1.0),
        "outer.inner": pytest.approx(2**2 + 2),
    }


def test_function_missing_from_coverage_counts_as_uncovered(tmp_path) -> None:
    module = tmp_path / "module.py"
    module.write_text("def lonely(x):\n    return 1 if x else 2\n", encoding="utf-8")

    assert [score for _, _, score in scores(_coverage(str(module), {}))] == [pytest.approx(6.0)]


def test_main_fails_only_when_a_function_reaches_the_limit(tmp_path, capsys) -> None:
    module = tmp_path / "module.py"
    module.write_text(SOURCE, encoding="utf-8")
    report_path = tmp_path / "coverage.json"
    covered = {"branchy": (6, 100.0)}
    report_path.write_text(json.dumps(_coverage(str(module), covered)), encoding="utf-8")

    assert main([str(report_path), "--limit", "10"]) == 0
    # branchy sin cobertura da 12: pasa el límite.
    report_path.write_text(json.dumps(_coverage(str(module), {"branchy": (6, 0.0)})))
    assert main([str(report_path), "--limit", "10"]) == 1
    assert "branchy" in capsys.readouterr().out


def test_a_function_exactly_at_the_limit_fails(tmp_path) -> None:
    module = tmp_path / "module.py"
    module.write_text(SOURCE, encoding="utf-8")
    report_path = tmp_path / "coverage.json"
    # branchy sin cobertura da exactamente 12.
    report_path.write_text(json.dumps(_coverage(str(module), {"branchy": (6, 0.0)})))

    assert main([str(report_path), "--limit", "12"]) == 1
    assert main([str(report_path), "--limit", "12.5"]) == 0
