"""CRAP por función: complejidad (radon) cruzada con cobertura (coverage.py en JSON).

CRAP = complejidad² × (1 − cobertura)³ + complejidad. Una función simple y probada da poco; una
enredada y sin pruebas da mucho. Falla si alguna función llega al límite.

Uso: python tools/crap.py coverage.json --limit 10
"""

import argparse
import json
import sys
from collections.abc import Iterator
from pathlib import Path

from radon.visitors import ComplexityVisitor, Function


def crap(complexity: int, percent_covered: float) -> float:
    uncovered = 1 - percent_covered / 100
    return complexity**2 * uncovered**3 + complexity


def _functions(blocks, prefix: str = "") -> Iterator[tuple[str, Function]]:
    # Funciones, métodos de clases y funciones internas (closures), con nombre completo.
    for block in blocks:
        if isinstance(block, Function):
            name = f"{prefix}{block.fullname}"
            yield name, block
            yield from _functions(block.closures, f"{name}.")
        else:
            yield from _functions(block.methods, prefix)


def scores(report: dict) -> Iterator[tuple[str, str, float]]:
    """(función, archivo, CRAP) de cada función de los archivos medidos."""
    for path, data in report["files"].items():
        # radon y coverage nombran distinto algunas funciones: se empatan por la línea donde
        # empiezan. Una función que coverage no conoce cuenta como sin cubrir.
        covered = {
            info["start_line"]: info["summary"]["percent_covered"]
            for info in data["functions"].values()
            if "start_line" in info
        }
        visitor = ComplexityVisitor.from_code(Path(path).read_text(encoding="utf-8"))
        for name, block in _functions(visitor.functions + visitor.classes):
            yield name, path, crap(block.complexity, covered.get(block.lineno, 0.0))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", help="reporte JSON de coverage.py")
    parser.add_argument("--limit", type=float, default=10.0)
    args = parser.parse_args(argv)
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    failing = [item for item in scores(report) if item[2] >= args.limit]
    for name, path, score in sorted(failing, key=lambda item: -item[2]):
        print(f"CRAP {score:6.1f}  {name}  ({path})")
    print(f"{len(failing)} funciones con CRAP de {args.limit:g} o más.")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
