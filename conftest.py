"""Solo para mutmut: durante la mutación, las pruebas deben importar el código mutado.

mutmut copia el código a mutants/ y corre pytest desde ahí, pero solo sabe agregar mutants/src al
camino de importación. Aquí cada paquete tiene su propio src/, así que se agregan todos. Fuera de
mutmut este archivo no hace nada.
"""

import sys
from pathlib import Path

if Path.cwd().name == "mutants":
    for source in sorted(Path.cwd().glob("*/*/src"), reverse=True):
        sys.path.insert(0, str(source))
